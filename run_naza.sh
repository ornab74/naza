#!/data/data/com.termux/files/usr/bin/bash
set -Eeuo pipefail
IFS=$'\n\t'
umask 077

PREFIX="${PREFIX:-/data/data/com.termux/files/usr}"
HOME="${HOME:-/data/data/com.termux/files/home}"
APP="$HOME/naza"
VENV="$APP/venv-termux"
OQS="$HOME/.local/liboqs-0.14.0"

safe_file() {
  local p="$1" owner mode
  [ -f "$p" ] || return 1
  [ ! -L "$p" ] || return 1
  owner="$(stat -c %u "$p")" || return 1
  mode="$(stat -c %a "$p")" || return 1
  [ "$owner" = "$(id -u)" ] || [ "$owner" = 0 ] || return 1
  [ $((8#$mode & 8#022)) -eq 0 ] || return 1
}

[ -x "$VENV/bin/python" ] || { echo "ERROR: native Naza venv missing" >&2; exit 1; }
safe_file "$VENV/bin/python" || { echo "ERROR: unsafe Python runtime permissions" >&2; exit 1; }
OQS_LIB="$(find "$OQS/lib" -maxdepth 1 -name 'liboqs.so*' -print -quit 2>/dev/null || true)"
[ -n "$OQS_LIB" ] && safe_file "$OQS_LIB" || { echo "ERROR: pinned liboqs backend missing/unsafe" >&2; exit 1; }

export LD_PRELOAD="$PREFIX/lib/libtermux-exec.so"
export VIRTUAL_ENV="$VENV"
export PATH="$VENV/bin:$PATH"
unset PYTHONHOME PYTHONPATH PYTHONSTARTUP PYTHONINSPECT
export OQS_INSTALL_PATH="$OQS"
export LD_LIBRARY_PATH="$OQS/lib${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"
export NAZA_CRYPTO_MODE=tri
export NAZA_REQUIRE_PROCESS_HARDENING=1
export PYTHONUNBUFFERED=1
ulimit -c 0 2>/dev/null || true
cd "$APP"
"$VENV/bin/python" "$APP/naza_crypto_preflight.py"
exec "$VENV/bin/python" -u "$APP/main.py" "$@"
