#!/usr/bin/env bash
# Native Ubuntu/Debian installer for SpookyNaza + pinned liboqs.
set -euo pipefail

APP_DIR="${NAZA_APP_DIR:-$HOME/naza}"
REPO_URL="${NAZA_REPO_URL:-https://github.com/ornab74/naza.git}"
NAZA_REF="${NAZA_REF:-main}"
VENV_DIR="$APP_DIR/venv"

sudo apt update
sudo apt upgrade -y
sudo apt install -y \
  git curl ca-certificates build-essential cmake ninja-build pkg-config libssl-dev \
  python3 python3-pip python3-venv python3-dev

if [ -d "$APP_DIR/.git" ]; then
  git -C "$APP_DIR" fetch --prune origin "$NAZA_REF"
else
  rm -rf "$APP_DIR"
  git clone "$REPO_URL" "$APP_DIR"
  git -C "$APP_DIR" fetch --prune origin "$NAZA_REF"
fi
git -C "$APP_DIR" checkout --detach FETCH_HEAD

python3 -m venv "$VENV_DIR"
. "$VENV_DIR/bin/activate"
python -m pip install --upgrade pip setuptools wheel

if [ -f "$APP_DIR/requirements.txt" ]; then
  python -m pip install --require-hashes -r "$APP_DIR/requirements.txt"
elif [ -f "$APP_DIR/requirements.in" ]; then
  python -m pip install -r "$APP_DIR/requirements.in"
else
  python -m pip install \
    'llama-cpp-python==0.3.1' 'httpx==0.28.0' 'aiosqlite==0.21.0' 'cryptography==46.0.1'
fi

chmod +x "$APP_DIR/install_liboqs_0.14.0.sh" "$APP_DIR/run_naza.sh"
export PYTHON_BIN="$VENV_DIR/bin/python"
"$APP_DIR/install_liboqs_0.14.0.sh"

export OQS_INSTALL_PATH="$HOME/.local/liboqs-0.14.0"
export LD_LIBRARY_PATH="$OQS_INSTALL_PATH/lib${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"
export NAZA_CRYPTO_MODE=tri
"$VENV_DIR/bin/python" - <<'PY'
import oqs
import spooky_trihybrid
mechs = set(oqs.get_enabled_kem_mechanisms())
missing = {"ML-KEM-1024", "HQC-256"} - mechs
if missing:
    raise SystemExit("SpookyNaza install failed; missing OQS mechanisms: " + ", ".join(sorted(missing)))
print("SpookyNaza default verified: tri-hybrid NKEY4 + ML-KEM-1024 + HQC-256 + X25519")
PY

echo
echo "Installation complete. Start Naza with:"
echo "  $APP_DIR/run_naza.sh"
