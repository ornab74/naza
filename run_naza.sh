#!/usr/bin/env bash
set -euo pipefail
APP_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENV_DIR="${NAZA_VENV:-$APP_DIR/venv}"
OQS_PREFIX="${OQS_INSTALL_PATH:-$HOME/.local/liboqs-0.14.0}"

if [ ! -x "$VENV_DIR/bin/python" ]; then
  echo "ERROR: Naza virtual environment not found at $VENV_DIR" >&2
  echo "Run the installer first." >&2
  exit 1
fi
if [ ! -f "$OQS_PREFIX/lib/liboqs.so" ] && ! find "$OQS_PREFIX/lib" -maxdepth 1 -name 'liboqs.so*' -print -quit 2>/dev/null | grep -q .; then
  echo "ERROR: pinned SpookyNaza liboqs backend not found at $OQS_PREFIX" >&2
  exit 1
fi

export OQS_INSTALL_PATH="$OQS_PREFIX"
export LD_LIBRARY_PATH="$OQS_PREFIX/lib${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"
export NAZA_CRYPTO_MODE="${NAZA_CRYPTO_MODE:-tri}"
export TERM="${TERM:-xterm-256color}"
export LANG="${LANG:-C.UTF-8}"
export PYTHONUNBUFFERED=1
cd "$APP_DIR"
exec "$VENV_DIR/bin/python" -u main.py "$@"
