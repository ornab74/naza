#!/usr/bin/env bash
set -euo pipefail
umask 077
APP_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENV_DIR="$APP_DIR/venv"
OQS_PREFIX="$HOME/.local/liboqs-0.14.0"

safe_runtime_file() {
  local path="$1" resolved owner mode
  resolved="$(readlink -f -- "$path")" || return 1
  [ -f "$resolved" ] || return 1
  owner="$(stat -c %u "$resolved")" || return 1
  mode="$(stat -c %a "$resolved")" || return 1
  [ "$owner" = "$(id -u)" ] || [ "$owner" = "0" ] || return 1
  # Reject group/other write bits while allowing ordinary 755/644 files.
  [ $((8#$mode & 8#022)) -eq 0 ] || return 1
}

if [ ! -x "$VENV_DIR/bin/python" ]; then
  echo "ERROR: Naza virtual environment not found at $VENV_DIR" >&2
  echo "Run the installer first." >&2
  exit 1
fi
safe_runtime_file "$VENV_DIR/bin/python" || {
  echo "ERROR: Python runtime has unsafe ownership or permissions" >&2
  exit 1
}
OQS_LIBRARY="$(find "$OQS_PREFIX/lib" -maxdepth 1 -name 'liboqs.so*' -print -quit 2>/dev/null || true)"
if [ -z "$OQS_LIBRARY" ] || ! safe_runtime_file "$OQS_LIBRARY"; then
  echo "ERROR: pinned SpookyNaza liboqs backend not found at $OQS_PREFIX" >&2
  exit 1
fi

export OQS_INSTALL_PATH="$OQS_PREFIX"
unset LD_PRELOAD PYTHONPATH PYTHONHOME PYTHONINSPECT PYTHONSTARTUP
export LD_LIBRARY_PATH="$OQS_PREFIX/lib"
export NAZA_CRYPTO_MODE="tri"
export NAZA_REQUIRE_PROCESS_HARDENING=1
export TERM="${TERM:-xterm-256color}"
export LANG="${LANG:-C.UTF-8}"
export PYTHONUNBUFFERED=1
cd "$APP_DIR"
"$VENV_DIR/bin/python" "$APP_DIR/naza_crypto_preflight.py"
exec "$VENV_DIR/bin/python" -u main.py "$@"
