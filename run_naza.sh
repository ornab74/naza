#!/data/data/com.termux/files/usr/bin/bash
set -Eeuo pipefail
IFS=$'\n\t'
umask 077
PREFIX="${PREFIX:-/data/data/com.termux/files/usr}"
HOME="${HOME:-/data/data/com.termux/files/home}"
NAZA_DIR="$HOME/naza"
VENV="$NAZA_DIR/venv-termux"
OQS="$HOME/.local/liboqs-0.14.0"
ORBIT_SOURCE="$NAZA_DIR/Optus-X-positioning.csv"
export LD_PRELOAD="$PREFIX/lib/libtermux-exec.so"
[ -x "$VENV/bin/python" ] || { echo "ERROR: native Termux Python missing." >&2; exit 1; }
[ -f "$OQS/lib/liboqs.so" ] || { echo "ERROR: native liboqs missing: $OQS/lib/liboqs.so" >&2; exit 1; }
export VIRTUAL_ENV="$VENV"; export PATH="$VENV/bin:$PATH"
unset PYTHONHOME PYTHONPATH PYTHONSTARTUP PYTHONINSPECT
export OQS_INSTALL_PATH="$OQS"
[ -f "$ORBIT_SOURCE" ] && [ ! -L "$ORBIT_SOURCE" ] || { echo "ERROR: calibrated orbit CSV missing or unsafe" >&2; exit 1; }
export NAZA_ORBIT_SOURCE_CSV="$ORBIT_SOURCE"
LLAMA_PKG="$($VENV/bin/python - <<'PY'
import sysconfig
from pathlib import Path
print(Path(sysconfig.get_paths()["purelib"]) / "llama_cpp")
PY
)"
LLAMA_LIB_DIR="$(find "$LLAMA_PKG" -type f -name 'libllama.so*' -print -quit 2>/dev/null | xargs -r dirname)"
[ -n "$LLAMA_LIB_DIR" ] || { echo "ERROR: llama.cpp native library not found" >&2; exit 1; }
export LLAMA_CPP_LIB_PATH="$LLAMA_LIB_DIR"
export LD_LIBRARY_PATH="$LLAMA_LIB_DIR:$OQS/lib${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"
unset HTTP_PROXY HTTPS_PROXY ALL_PROXY http_proxy https_proxy all_proxy
export NAZA_OFFLINE_MODE="${NAZA_OFFLINE_MODE:-1}"
export NAZA_CRYPTO_MODE=tri
export NAZA_REQUIRE_PROCESS_HARDENING=1
export PYTHONUNBUFFERED=1
ulimit -c 0 2>/dev/null || true
cd "$NAZA_DIR"
"$VENV/bin/python" "$NAZA_DIR/naza_crypto_preflight.py"
exec "$VENV/bin/python" -u "$NAZA_DIR/main.py" "$@"
