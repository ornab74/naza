name: Lock requirements + PQ-sign lock manifest (no wheelhouse)

on:
  workflow_dispatch:
  push:
    paths:
      - requirements.in
      - main.py
      - main_foodwater.py
      - .github/workflows/lock-and-pq-sign-lockfile.yml

jobs:
  lock_and_pq_sign:
    runs-on: ubuntu-latest

    container:
      image: python:3.12-slim

    defaults:
      run:
        shell: bash

    steps:
      # ------------------------------------------------------------
      # CHECKOUT
      # ------------------------------------------------------------
      - name: Checkout repo
        uses: actions/checkout@v4

      # ------------------------------------------------------------
      # SYSTEM TOOLS
      # ------------------------------------------------------------
      - name: Install system tools
        run: |
          set -euo pipefail
          apt-get update
          apt-get install -y --no-install-recommends \
            ca-certificates \
            curl \
            coreutils \
            cmake \
            ninja-build \
            build-essential \
            pkg-config \
            git
          rm -rf /var/lib/apt/lists/*

      # ------------------------------------------------------------
      # PYTHON TOOLING
      # ------------------------------------------------------------
      - name: Upgrade pip + install pip-tools
        run: |
          set -euo pipefail
          python -m pip install --upgrade pip
          pip install pip-tools

      # ------------------------------------------------------------
      # LOCK DEPENDENCIES (HASH-LOCKED)
      # ------------------------------------------------------------
      - name: Generate hash-locked requirements.txt
        run: |
          set -euo pipefail
          pip-compile \
            --generate-hashes \
            --resolver=backtracking \
            --output-file requirements.txt \
            requirements.in

      # ------------------------------------------------------------
      # BUILD + INSTALL LIBOQS (FROM SOURCE)
      # ------------------------------------------------------------
      - name: Build + install liboqs
        run: |
          set -euo pipefail

          LIBOQS_VERSION="0.14.0"
          LIBOQS_URL="https://github.com/open-quantum-safe/liboqs/archive/refs/tags/${LIBOQS_VERSION}.tar.gz"

          curl -fsSL -o /tmp/liboqs.tar.gz "${LIBOQS_URL}"
          LIBOQS_SHA256="$(sha256sum /tmp/liboqs.tar.gz | awk '{print $1}')"

          echo "LIBOQS_VERSION=${LIBOQS_VERSION}" >> "$GITHUB_ENV"
          echo "LIBOQS_URL=${LIBOQS_URL}" >> "$GITHUB_ENV"
          echo "LIBOQS_SHA256=${LIBOQS_SHA256}" >> "$GITHUB_ENV"

          mkdir -p /tmp/liboqs-src
          tar -xzf /tmp/liboqs.tar.gz -C /tmp/liboqs-src --strip-components=1

          cmake -S /tmp/liboqs-src -B /tmp/liboqs-src/build \
            -DCMAKE_INSTALL_PREFIX=/usr/local \
            -DBUILD_SHARED_LIBS=ON \
            -DOQS_USE_OPENSSL=OFF \
            -DCMAKE_POSITION_INDEPENDENT_CODE=ON \
            -G Ninja

          cmake --build /tmp/liboqs-src/build --parallel
          cmake --install /tmp/liboqs-src/build
          ldconfig

          rm -rf /tmp/liboqs-src /tmp/liboqs.tar.gz

      # ------------------------------------------------------------
      # PYTHON OQS BINDINGS
      # ------------------------------------------------------------
      - name: Install liboqs-python
        run: |
          set -euo pipefail
          pip install "liboqs-python==0.14.1"
          python - <<'PY'
          import oqs
          print("oqs OK:", oqs.get_enabled_sig_mechanisms())
          PY

      # ------------------------------------------------------------
      # PROVENANCE HEADER (BEFORE HASHING & SIGNING)
      # ------------------------------------------------------------
      - name: Prepend provenance header
        run: |
          set -euo pipefail
          {
            echo "# liboqs_version=${LIBOQS_VERSION}"
            echo "# liboqs_tarball_sha256=${LIBOQS_SHA256}"
            echo "# liboqs_tarball_url=${LIBOQS_URL}"
            echo "# pq_signature_alg=Dilithium2"
            echo "# pq_manifest=lock.manifest.json"
            echo "# pq_signature=lock.manifest.pqsig"
            echo "# pq_pubkey=pq_pubkey.b64"
            echo "# generated_by=github_actions_lock_and_pq_sign"
            echo
            cat requirements.txt
          } > requirements.tmp
          mv requirements.tmp requirements.txt

      # ------------------------------------------------------------
      # CANONICAL MANIFEST + PQ SIGN (DEPS + ENTRYPOINTS)
      # ------------------------------------------------------------
      - name: Create canonical manifest + PQ-sign (deps + entrypoints)
        run: |
          set -euo pipefail

          cat > /tmp/pq_sign_lock.py <<'PY'
          import base64
          import hashlib
          import json
          import os
          import re
          import sys
          import oqs

          ALG = "Dilithium2"
          REQ = "requirements.txt"
          ENTRIES = ["main.py", "main_foodwater.py"]

          def sha256(path):
              with open(path, "rb") as f:
                  return hashlib.sha256(f.read()).hexdigest()

          # --------------------------------------------------------
          # REQUIREMENTS HASH
          # --------------------------------------------------------
          if not os.path.exists(REQ):
              sys.exit("missing requirements.txt")

          req_sha = sha256(REQ)

          # --------------------------------------------------------
          # ENTRYPOINT HASHES
          # --------------------------------------------------------
          entry_hashes = {}
          for e in ENTRIES:
              if not os.path.exists(e):
                  sys.exit(f"missing entrypoint: {e}")
              entry_hashes[e] = "sha256:" + sha256(e)

          # --------------------------------------------------------
          # PINNED PACKAGES (CANONICAL ORDER)
          # --------------------------------------------------------
          pkg_re = re.compile(r"^([A-Za-z0-9_.-]+)==([^\s\\]+)")
          pinned = []

          with open(REQ, encoding="utf-8") as f:
              for line in f:
                  m = pkg_re.match(line.strip())
                  if m:
                      pinned.append({
                          "name": m.group(1).lower(),
                          "version": m.group(2),
                      })

          pinned.sort(key=lambda x: x["name"])

          # --------------------------------------------------------
          # CANONICAL MANIFEST
          # --------------------------------------------------------
          manifest = {
              "format": "pq-lock-manifest-v1",
              "pq_alg": ALG,
              "requirements_txt_sha256": req_sha,
              "entrypoints": entry_hashes,
              "pinned": pinned,
          }

          canonical = json.dumps(
              manifest,
              sort_keys=True,
              separators=(",", ":"),
          ).encode("utf-8")

          # --------------------------------------------------------
          # PQ SIGN
          # --------------------------------------------------------
          with oqs.Signature(ALG) as signer:
              pub = signer.generate_keypair()
              sig = signer.sign(canonical)

          with open("lock.manifest.json", "wb") as f:
              f.write(canonical + b"\n")

          with open("lock.manifest.pqsig", "wb") as f:
              f.write(sig)

          with open("pq_pubkey.b64", "w", encoding="utf-8") as f:
              f.write(base64.b64encode(pub).decode("ascii") + "\n")

          # --------------------------------------------------------
          # SELF-VERIFY (FAIL-CLOSED)
          # --------------------------------------------------------
          with oqs.Signature(ALG) as verifier:
              if not verifier.verify(canonical, sig, pub):
                  sys.exit("FATAL: PQ self-verification failed")

          print("OK: requirements + entrypoints PQ-signed")
          PY

          python /tmp/pq_sign_lock.py

      # ------------------------------------------------------------
      # ARTIFACT UPLOAD
      # ------------------------------------------------------------
      - name: Upload PQ-locked materials
        uses: actions/upload-artifact@v4
        with:
          name: pq-locked-naza-bundle
          path: |
            requirements.txt
            lock.manifest.json
            lock.manifest.pqsig
            pq_pubkey.b64
          retention-days: 30
