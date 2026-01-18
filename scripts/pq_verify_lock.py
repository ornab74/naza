#!/usr/bin/env python3
import base64
import hashlib
import json
import sys
from pathlib import Path

import oqs

REQ_PATH = Path("requirements.txt")
MANIFEST_PATH = Path("lock.manifest.json")
SIG_PATH = Path("lock.manifest.pqsig")
PUBKEY_PATH = Path("pq_pubkey.b64")


def read_required(path: Path) -> bytes:
    if not path.exists():
        raise FileNotFoundError(f"Missing required file: {path}")
    return path.read_bytes()


def parse_header_value(lines: list[str], prefix: str) -> str:
    for line in lines:
        if line.startswith(prefix):
            return line[len(prefix) :].strip()
    return ""


def main() -> int:
    req_bytes = read_required(REQ_PATH)
    manifest_bytes = read_required(MANIFEST_PATH)
    sig_bytes = read_required(SIG_PATH)
    pubkey_b64 = read_required(PUBKEY_PATH)

    req_text = req_bytes.decode("utf-8", errors="replace").splitlines()
    req_alg = parse_header_value(req_text, "# pq_signature_alg=")
    if not req_alg:
        raise ValueError("requirements.txt missing # pq_signature_alg header")

    manifest = json.loads(manifest_bytes)
    man_alg = manifest.get("pq_alg")
    man_req_sha = manifest.get("requirements_txt_sha256")
    if not man_alg or not man_req_sha:
        raise ValueError("lock.manifest.json missing pq_alg or requirements_txt_sha256")

    if man_alg != req_alg:
        raise ValueError(f"Algorithm mismatch: requirements={req_alg} manifest={man_alg}")

    req_sha = hashlib.sha256(req_bytes).hexdigest()
    if req_sha != man_req_sha:
        raise ValueError(
            "requirements.txt SHA256 mismatch: "
            f"manifest={man_req_sha} actual={req_sha}"
        )

    pubkey = base64.b64decode(pubkey_b64.strip())
    with oqs.Signature(man_alg) as verifier:
        ok = verifier.verify(manifest_bytes, sig_bytes, pubkey)
    if not ok:
        raise ValueError("PQ signature verification failed")

    print("OK: PQ lock manifest verified.")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as exc:  # noqa: BLE001
        print(f"ERROR: {exc}", file=sys.stderr)
        sys.exit(1)
