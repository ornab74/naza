#!/data/data/com.termux/files/usr/bin/bash
# ============================================================
# Termux → Ubuntu proot → Naza FULL AUTO-SETUP + AUTO-START
# + PQ LOCK VERIFICATION (Dilithium2) BEFORE INSTALLING DEPS
# ============================================================

set -euo pipefail

echo "Updating Termux packages..."
pkg update -y && pkg upgrade -y
pkg install -y bash bzip2 coreutils curl file findutils gawk gzip ncurses-utils proot sed tar util-linux xz-utils git wget

echo "Removing any old proot-distro..."
proot-distro remove ubuntu 2>/dev/null || true
rm -rf "$HOME/proot-distro" 2>/dev/null || true

echo "Cloning OLD working proot-distro commit (ca53fee – full TTY support)..."
cd "$HOME"
git clone https://github.com/termux/proot-distro.git
cd "$HOME/proot-distro"
git checkout ca53fee288be8f46ee0e4fc8ee23934023472054

echo "Installing proot-distro from this commit..."
chmod +x install.sh
./install.sh

echo "Installing Ubuntu (24.04 rootfs)..."
proot-distro install ubuntu

echo "Creating TMP dir..."
export PROOT_TMP_DIR="$HOME/tmp"
mkdir -p "$PROOT_TMP_DIR"

echo "Setting up sudouser + Python + Naza repo + PQ verification..."
proot-distro login ubuntu -- <<'EOF'
set -euo pipefail

apt update && apt upgrade -y

# Base tools + build tools (needed to build liboqs verifier)
apt install -y \
  sudo python3 python3-pip python3-venv git nano curl ca-certificates \
  build-essential cmake ninja-build pkg-config libssl-dev

# Create sudouser (no password)
adduser --disabled-password --gecos "" sudouser
usermod -aG sudo sudouser
echo "sudouser ALL=(ALL) NOPASSWD:ALL" >> /etc/sudoers

# --- PQ verification + install as sudouser ---
su - sudouser -c '
set -euo pipefail

mkdir -p ~/naza
cd ~/naza

# Clone / update repo
if [ -d .git ]; then
  git pull --ff-only
else
  git clone https://github.com/ornab74/naza.git ./
fi

# Require PQ lock bundle to be present in repo root:
#   requirements.txt
#   lock.manifest.json
#   lock.manifest.pqsig
#   pq_pubkey.b64
for f in requirements.txt lock.manifest.json lock.manifest.pqsig pq_pubkey.b64; do
  if [ ! -f "$f" ]; then
    echo "ERROR: Missing $f in ~/naza"
    echo "Refusing to install dependencies without PQ lock verification."
    exit 1
  fi
done

# ---- PQ VERIFY SCRIPT (build liboqs + verify Dilithium2 signature) ----
cat > pq_verify_lock.sh <<'"'"'SH'"'"'
#!/usr/bin/env bash
set -euo pipefail

REQ="requirements.txt"
MAN="lock.manifest.json"
SIG="lock.manifest.pqsig"
PUB_B64="pq_pubkey.b64"

# Pull liboqs metadata + expected algorithm from requirements.txt header
OQS_VER="$(grep -E "^# liboqs_version=" "$REQ" | head -n1 | cut -d= -f2-)"
OQS_SHA="$(grep -E "^# liboqs_tarball_sha256=" "$REQ" | head -n1 | cut -d= -f2-)"
OQS_URL="$(grep -E "^# liboqs_tarball_url=" "$REQ" | head -n1 | cut -d= -f2-)"
REQ_PQ_ALG="$(grep -E "^# pq_signature_alg=" "$REQ" | head -n1 | cut -d= -f2-)"

if [ -z "${OQS_VER:-}" ] || [ -z "${OQS_SHA:-}" ] || [ -z "${OQS_URL:-}" ] || [ -z "${REQ_PQ_ALG:-}" ]; then
  echo "ERROR: Missing PQ/liboqs header metadata in $REQ"
  exit 1
fi

# Parse manifest: pq_alg + requirements_txt_sha256
read -r MAN_PQ_ALG MAN_REQ_SHA < <(python3 - <<PY
import json
with open("$MAN","rb") as f:
    d=json.load(f)
print(d.get("pq_alg",""), d.get("requirements_txt_sha256",""))
PY
)

if [ -z "${MAN_PQ_ALG:-}" ] || [ -z "${MAN_REQ_SHA:-}" ]; then
  echo "ERROR: Manifest missing pq_alg and/or requirements_txt_sha256"
  exit 1
fi

if [ "$REQ_PQ_ALG" != "$MAN_PQ_ALG" ]; then
  echo "ERROR: Algorithm mismatch: requirements=$REQ_PQ_ALG manifest=$MAN_PQ_ALG"
  exit 1
fi

# Verify requirements.txt sha256 matches manifest
CALC_REQ_SHA="$(sha256sum "$REQ" | awk "{print \$1}")"
if [ "$CALC_REQ_SHA" != "$MAN_REQ_SHA" ]; then
  echo "ERROR: requirements.txt SHA256 mismatch!"
  echo "  manifest: $MAN_REQ_SHA"
  echo "  actual:   $CALC_REQ_SHA"
  exit 1
fi

# Prepare workdir
WD=".pqverify"
mkdir -p "$WD"
cd "$WD"

# Decode public key
base64 -d "../$PUB_B64" > pq_pubkey.bin

# Download + verify liboqs tarball
TARBALL="liboqs-${OQS_VER}.tar.gz"
if [ ! -f "$TARBALL" ]; then
  echo "Downloading liboqs ${OQS_VER}..."
  curl -fsSL "$OQS_URL" -o "$TARBALL"
fi

echo "${OQS_SHA}  ${TARBALL}" | sha256sum -c -

# Extract
SRC_DIR="liboqs-${OQS_VER}-src"
rm -rf "$SRC_DIR"
mkdir -p "$SRC_DIR"
tar -xzf "$TARBALL" -C "$SRC_DIR" --strip-components=1

# Build liboqs
echo "Building liboqs..."
cmake -S "$SRC_DIR" -B "$SRC_DIR/build" -DCMAKE_BUILD_TYPE=Release
cmake --build "$SRC_DIR/build" -j"$(nproc)"

# C verifier using liboqs
cat > verify_pq.c <<'"'"'C'"'"'
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <oqs/oqs.h>

static unsigned char *read_file(const char *path, size_t *len_out) {
  FILE *f = fopen(path, "rb");
  if (!f) return NULL;
  if (fseek(f, 0, SEEK_END) != 0) { fclose(f); return NULL; }
  long sz = ftell(f);
  if (sz < 0) { fclose(f); return NULL; }
  rewind(f);
  unsigned char *buf = (unsigned char *)malloc((size_t)sz);
  if (!buf) { fclose(f); return NULL; }
  size_t n = fread(buf, 1, (size_t)sz, f);
  fclose(f);
  if (n != (size_t)sz) { free(buf); return NULL; }
  *len_out = (size_t)sz;
  return buf;
}

int main(int argc, char **argv) {
  if (argc != 5) {
    fprintf(stderr, "Usage: %s <ALG> <MANIFEST_JSON> <SIG_BIN> <PUBKEY_BIN>\n", argv[0]);
    return 2;
  }
  const char *alg = argv[1];
  const char *manifest_path = argv[2];
  const char *sig_path = argv[3];
  const char *pk_path = argv[4];

  OQS_SIG *sig = OQS_SIG_new(alg);
  if (sig == NULL) {
    fprintf(stderr, "ERROR: OQS_SIG_new failed for alg=%s\n", alg);
    return 3;
  }

  size_t msg_len=0, sig_len=0, pk_len=0;
  unsigned char *msg = read_file(manifest_path, &msg_len);
  unsigned char *sigbuf = read_file(sig_path, &sig_len);
  unsigned char *pk = read_file(pk_path, &pk_len);

  if (!msg || !sigbuf || !pk) {
    fprintf(stderr, "ERROR: failed to read one or more files\n");
    OQS_SIG_free(sig);
    free(msg); free(sigbuf); free(pk);
    return 4;
  }

  if (pk_len != sig->length_public_key) {
    fprintf(stderr, "ERROR: public key length mismatch (got=%zu expected=%zu)\n",
            pk_len, sig->length_public_key);
    OQS_SIG_free(sig);
    free(msg); free(sigbuf); free(pk);
    return 5;
  }
  if (sig_len != sig->length_signature) {
    fprintf(stderr, "ERROR: signature length mismatch (got=%zu expected=%zu)\n",
            sig_len, sig->length_signature);
    OQS_SIG_free(sig);
    free(msg); free(sigbuf); free(pk);
    return 6;
  }

  OQS_STATUS ok = OQS_SIG_verify(sig, msg, msg_len, sigbuf, sig_len, pk);
  OQS_SIG_free(sig);
  free(msg); free(sigbuf); free(pk);

  if (ok != OQS_SUCCESS) {
    fprintf(stderr, "ERROR: PQ signature verification FAILED\n");
    return 7;
  }

  printf("OK: PQ signature verified (%s) and requirements.txt sha256 matches manifest\n", alg);
  return 0;
}
C

# Compile verifier
echo "Compiling verifier..."
gcc -O2 -I "$SRC_DIR/build/include" -I "$SRC_DIR/include" verify_pq.c \
  -L "$SRC_DIR/build/lib" -loqs -lcrypto -lpthread -ldl -o pq_verify_bin

# Run verification (uses LD_LIBRARY_PATH to find liboqs)
echo "Verifying PQ signature..."
LD_LIBRARY_PATH="$SRC_DIR/build/lib${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}" \
  ./pq_verify_bin "$REQ_PQ_ALG" "../$MAN" "../$SIG" pq_pubkey.bin
SH

chmod +x pq_verify_lock.sh
./pq_verify_lock.sh

# Only after verification succeeds: install deps with hash enforcement
python3 -m venv venv
# shellcheck disable=SC1091
source venv/bin/activate
pip install --upgrade pip
pip install --require-hashes -r requirements.txt

chmod +x main.py || true
echo "PQ-verified setup complete inside Ubuntu"
'

echo "Setup complete inside Ubuntu"
EOF

# ============================================================
# FINAL STEP: FORCE AUTO-START WITH YOUR EXACT BANNER + FULL TTY
# ============================================================

cat > ~/.bashrc <<'BASHRC'
# === AUTO-START SECURELLM IN UBUNTU PROOT (naza folder + venv) ===
if [ -z "$NAZA_STARTED" ] && [ "$PWD" = "$HOME" ] && [ -z "$SSH_CLIENT" ] && [ -z "$TMUX" ]; then
    export NAZA_STARTED=1

    echo ""
    echo "╔══════════════════════════════════════════════════════════╗"
    echo "║          Starting SecureLLM TUI (naza/main.py)           ║"
    echo "║        Ubuntu proot → /home/sudouser/naza                ║"
    echo "╚══════════════════════════════════════════════════════════╝"
    echo "   Type 'exit' twice to return to Termux"
    echo ""

    proot-distro login ubuntu --user sudouser --shared-tmp -- bash -c "
        cd /home/sudouser/naza || exit 1

        # Activate venv
        source venv/bin/activate || exit 1

        # Fix terminal + locale + unbuffered output
        export TERM=xterm-256color
        export LANG=C.UTF-8
        export PYTHONUNBUFFERED=1

        clear
        echo 'Starting main.py in venv...'
        exec python -u main.py
    "

    clear
    echo "Returned to Termux."
fi
BASHRC

echo "alias naza='proot-distro login ubuntu --user sudouser -- bash -c \"cd ~/naza && source venv/bin/activate && python -u main.py\"'" >> ~/.bashrc

echo "--------------------------------------------------------------"
echo "ALL DONE!"
echo "Close and reopen Termux (or run: bash)"
echo "SecureLLM will auto-start. Dependencies are installed ONLY after PQ verification passes."
echo "--------------------------------------------------------------"
