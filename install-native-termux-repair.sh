#!/data/data/com.termux/files/usr/bin/bash
set -Eeuo pipefail
IFS=$'\n\t'
umask 077

PREFIX="${PREFIX:-/data/data/com.termux/files/usr}"
HOME="${HOME:-/data/data/com.termux/files/home}"
NAZA_DIR="${NAZA_DIR:-$HOME/naza}"
VENV="$NAZA_DIR/venv-termux"
OQS_HOME="$HOME/.local/liboqs-0.14.0"
KEYSTORE="$PREFIX/bin/termux-keystore"
TERMUX_EXEC="$PREFIX/lib/libtermux-exec.so"
LLAMA_VERSION="0.3.1"

say(){ printf '\n==> %s\n' "$*"; }
die(){ printf 'ERROR: %s\n' "$*" >&2; exit 1; }
need(){ command -v "$1" >/dev/null 2>&1 || die "required command missing: $1"; }

[ -d "$NAZA_DIR" ] || die "Naza checkout not found at $NAZA_DIR"
[ ! -L "$NAZA_DIR" ] || die "refusing symlinked Naza directory"
chmod 700 "$NAZA_DIR"

# Non-destructive repair: never delete/rekey existing key, history, models, or app data.
for p in .enc_key chat_history.db.aes models; do
    [ ! -e "$NAZA_DIR/$p" ] || printf 'Preserving existing: %s\n' "$NAZA_DIR/$p"
done

say "Installing native Termux prerequisites"
pkg update -y
pkg install -y python clang cmake ninja make git curl rust binutils coreutils findutils grep sed tar gzip unzip termux-api
need python; need clang; need cmake; need ninja; need git
[ -x "$KEYSTORE" ] || die "termux-keystore unavailable; repair matching Termux:API app/package"
[ -f "$TERMUX_EXEC" ] || die "libtermux-exec.so missing"

say "Creating/reusing native Python venv"
[ -x "$VENV/bin/python" ] || python -m venv "$VENV"
PY="$VENV/bin/python"
"$PY" -m pip install --upgrade pip setuptools wheel
"$PY" -m pip install 'httpx==0.28.1' 'aiosqlite==0.22.1' 'numpy==2.5.3' 'MarkupSafe==3.0.3' 'diskcache==5.6.3' 'Jinja2==3.1.6' 'typing-extensions==4.16.0' 'cffi==2.1.1' 'pycparser==3.0'
"$PY" -m pip install --force-reinstall 'cryptography==46.0.5'

say "Installing/reusing minimal liboqs 0.14.0"
OQS_OK=0
if OQS_INSTALL_PATH="$OQS_HOME" LD_LIBRARY_PATH="$OQS_HOME/lib" "$PY" - <<'PY' >/dev/null 2>&1
import hmac, oqs
assert oqs.oqs_version() == '0.14.0'
assert {'ML-KEM-1024','HQC-256'}.issubset(set(oqs.get_enabled_kem_mechanisms()))
for name in ('ML-KEM-1024','HQC-256'):
    with oqs.KeyEncapsulation(name) as kem:
        pk=kem.generate_keypair(); ct,a=kem.encap_secret(pk); b=kem.decap_secret(ct)
        assert hmac.compare_digest(a,b)
PY
then OQS_OK=1; fi
if [ "$OQS_OK" -ne 1 ]; then
    PREFIX="$OQS_HOME" PYTHON_BIN="$PY" bash "$NAZA_DIR/install_liboqs_0.14.0.sh"
fi
export OQS_INSTALL_PATH="$OQS_HOME"
export LD_LIBRARY_PATH="$OQS_HOME/lib${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"

say "Building/verifying llama-cpp-python $LLAMA_VERSION for Android/Termux"
PURELIB="$($PY - <<'PY'
import sysconfig
print(sysconfig.get_paths()['purelib'])
PY
)"
LLAMA_PKG="$PURELIB/llama_cpp"
find_llama_lib(){ find "$LLAMA_PKG" -type f -name 'libllama.so*' -print -quit 2>/dev/null || true; }
llama_ok(){
    local lib="$(find_llama_lib)" dir
    [ -n "$lib" ] || return 1
    dir="$(dirname "$lib")"
    LLAMA_CPP_LIB_PATH="$dir" LD_LIBRARY_PATH="$dir:$OQS_HOME/lib${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}" "$PY" - "$lib" <<'PY' >/dev/null 2>&1
import ctypes, importlib.metadata as md, sys
assert md.version('llama-cpp-python') == '0.3.1'
ctypes.CDLL(sys.argv[1], mode=getattr(ctypes,'RTLD_GLOBAL',0))
import llama_cpp
from llama_cpp import Llama
assert callable(Llama)
PY
}
if ! llama_ok; then
    "$PY" -m pip uninstall -y llama-cpp-python 2>/dev/null || true
    export CMAKE_BUILD_PARALLEL_LEVEL=1
    export CMAKE_ARGS="-DCMAKE_BUILD_TYPE=Release -DGGML_NATIVE=OFF -DGGML_OPENMP=OFF"
    "$PY" -m pip install --no-cache-dir --no-binary llama-cpp-python "llama-cpp-python==$LLAMA_VERSION"
    EXT="$LLAMA_PKG/_ctypes_extensions.py"
    [ -f "$EXT" ] || die "llama_cpp/_ctypes_extensions.py missing after source build"
    "$PY" - "$EXT" <<'PY'
from pathlib import Path
import sys
p=Path(sys.argv[1]); s=p.read_text()
old='if sys.platform.startswith("linux") or sys.platform.startswith("freebsd"):'
new='if sys.platform.startswith("linux") or sys.platform.startswith("android") or sys.platform.startswith("freebsd"):'
if old in s and 'sys.platform.startswith("android")' not in s:
    p.write_text(s.replace(old,new,1))
PY
    llama_ok || die "llama-cpp-python built but Android native loader verification failed"
fi
LLAMA_LIB="$(find_llama_lib)"; [ -n "$LLAMA_LIB" ] || die "libllama.so missing"
LLAMA_LIB_DIR="$(dirname "$LLAMA_LIB")"

say "Configuring Android Keystore Gate 3"
if ! "$KEYSTORE" list 2>/dev/null | grep -q '"alias"[[:space:]]*:[[:space:]]*"naza-unlock"'; then
    "$KEYSTORE" generate naza-unlock -a RSA -s 2048 -u 10
fi
"$PREFIX/bin/python" - "$KEYSTORE" <<'PY'
import json, subprocess, sys
items=json.loads(subprocess.check_output([sys.argv[1],'list'], text=True))
for item in items:
    if item.get('alias')!='naza-unlock': continue
    auth=item.get('user_authentication') or {}
    good=(item.get('algorithm')=='RSA' and int(item.get('size',0))==2048 and bool(item.get('inside_secure_hardware')) and bool(auth.get('required')) and bool(auth.get('enforced_by_secure_hardware')) and int(auth.get('validity_duration_seconds',-1))==10)
    raise SystemExit(0 if good else 'naza-unlock does not satisfy Gate 3 hardware policy')
raise SystemExit('naza-unlock alias missing')
PY

say "Validating source and launchers"
for f in main.py naza_core.py naza_orbit_patch.py naza_orbit_sim.py naza_storage.py spooky_combiner.py spooky_trihybrid.py naza_crypto_preflight.py; do
    [ -f "$NAZA_DIR/$f" ] || die "missing $f"
done
[ -f "$NAZA_DIR/Optus-X-positioning.csv" ] || die "missing orbital simulation calibration CSV"
[ ! -L "$NAZA_DIR/Optus-X-positioning.csv" ] || die "refusing symlinked orbital CSV"
chmod 600 "$NAZA_DIR/Optus-X-positioning.csv"
"$PY" -m py_compile "$NAZA_DIR"/{main.py,naza_core.py,naza_orbit_patch.py,naza_orbit_sim.py,naza_storage.py,spooky_combiner.py,spooky_trihybrid.py,naza_crypto_preflight.py}
bash -n "$NAZA_DIR/run_naza.sh" "$NAZA_DIR/naza_unlock.sh" "$NAZA_DIR/install_liboqs_0.14.0.sh"
chmod 700 "$NAZA_DIR/run_naza.sh" "$NAZA_DIR/naza_unlock.sh" "$NAZA_DIR/install-native-termux-repair.sh" "$NAZA_DIR/install_liboqs_0.14.0.sh"

say "Running exact runtime preflight"
export VIRTUAL_ENV="$VENV"; export PATH="$VENV/bin:$PATH"
export LLAMA_CPP_LIB_PATH="$LLAMA_LIB_DIR"
export LD_LIBRARY_PATH="$LLAMA_LIB_DIR:$OQS_HOME/lib${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"
export LD_PRELOAD="$TERMUX_EXEC"; export NAZA_ORBIT_SOURCE_CSV="$NAZA_DIR/Optus-X-positioning.csv"
export NAZA_CRYPTO_MODE=tri; export NAZA_REQUIRE_PROCESS_HARDENING=1
unset PYTHONHOME PYTHONPATH PYTHONSTARTUP PYTHONINSPECT
unset HTTP_PROXY HTTPS_PROXY ALL_PROXY http_proxy https_proxy all_proxy
cd "$NAZA_DIR"
"$PY" "$NAZA_DIR/naza_crypto_preflight.py"

cat <<EOF

Native Termux reconciliation complete.
Preserved existing encrypted key/history/models/application data.
liboqs: 0.14.0, minimal ML-KEM-1024 + HQC-256, one-job build path.
llama-cpp-python: $LLAMA_VERSION, native Android loader verified.

Run:
  bash ~/naza/naza_unlock.sh
  bash ~/naza/run_naza.sh
EOF
