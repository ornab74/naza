#!/data/data/com.termux/files/usr/bin/bash
set -Eeuo pipefail
IFS=$'\n\t'
umask 077

PREFIX="${PREFIX:-/data/data/com.termux/files/usr}"
HOME="${HOME:-/data/data/com.termux/files/home}"
NAZA_DIR="${NAZA_DIR:-$HOME/naza}"
VENV="$NAZA_DIR/venv-termux"
OQS_VERSION="0.14.0"
OQS_PREFIX="$HOME/.local/liboqs-$OQS_VERSION"
OQS_TARBALL_SHA256="5b0df6138763b3fc4e385d58dbb2ee7c7c508a64a413d76a917529e3a9a207ea"
OQS_PY_REF="7906e7879a099fa34217035957d977314f99757d"
OQS_PY_SHA256="ed785fee58e43f20c042db97389ce63091b331278c24f63828c4b8dac0905f8c"
LLAMA_VERSION="0.3.1"
KEYSTORE="$PREFIX/bin/termux-keystore"
TERMUX_EXEC="$PREFIX/lib/libtermux-exec.so"
BACKUP_ROOT="$HOME/.naza-native-backups"
STAMP="$(date +%Y%m%d-%H%M%S)"
BACKUP_DIR="$BACKUP_ROOT/$STAMP"

say() { printf '\n==> %s\n' "$*"; }
warn() { printf 'WARNING: %s\n' "$*" >&2; }
die() { printf 'ERROR: %s\n' "$*" >&2; exit 1; }

backup_file() {
  local p="$1"
  [ -e "$p" ] || return 0
  mkdir -p "$BACKUP_DIR"
  cp -a -- "$p" "$BACKUP_DIR/$(basename "$p")"
}

sha256_file() {
  sha256sum "$1" | awk '{print $1}'
}

verify_sha256() {
  local p="$1" expected="$2" label="$3" got
  got="$(sha256_file "$p")"
  [ "$got" = "$expected" ] || die "$label SHA-256 mismatch: expected $expected got $got"
}

[ -d "$NAZA_DIR" ] || die "Naza checkout not found at $NAZA_DIR"
[ ! -L "$NAZA_DIR" ] || die "Refusing symbolic-link Naza directory"
chmod 700 "$NAZA_DIR"
mkdir -p "$BACKUP_ROOT"
chmod 700 "$BACKUP_ROOT"

# Native Termux executables need the Termux execution hook. Never preload libpython.
[ -f "$TERMUX_EXEC" ] || die "libtermux-exec.so is missing: $TERMUX_EXEC"
export LD_PRELOAD="$TERMUX_EXEC"
export PYTHONUNBUFFERED=1

say "1/10 Reconcile native Termux build prerequisites"
pkg update -y
pkg install -y \
  python python-pip clang cmake ninja make git curl rust binutils pkg-config \
  openssl libandroid-support libandroid-spawn coreutils findutils grep sed tar gzip unzip termux-api

[ -x "$KEYSTORE" ] || die "termux-keystore is unavailable; repair/install the matching Termux:API environment"

say "2/10 Create/reuse Naza native venv"
if [ ! -x "$VENV/bin/python" ]; then
  python -m venv "$VENV"
fi
PY="$VENV/bin/python"
[ -x "$PY" ] || die "venv Python missing: $PY"
"$PY" -m pip install --upgrade pip setuptools wheel

say "3/10 Install Android-compatible Python dependencies"
"$PY" -m pip install \
  'httpx==0.28.1' \
  'aiosqlite==0.22.1' \
  'numpy==2.5.3' \
  'MarkupSafe==3.0.3' \
  'diskcache==5.6.3' \
  'Jinja2==3.1.6' \
  'typing-extensions==4.16.0' \
  'cffi==2.1.1' \
  'pycparser==3.0'

# Explicitly keep removed packages out of the native environment.
"$PY" -m pip uninstall -y psutil pennylane pennylane-lightning rustworkx scipy scipy-openblas32 2>/dev/null || true

say "4/10 Discover or build minimal liboqs 0.14.0"
OQS_OK=0
if [ -f "$OQS_PREFIX/lib/liboqs.so" ]; then
  if OQS_INSTALL_PATH="$OQS_PREFIX" LD_LIBRARY_PATH="$OQS_PREFIX/lib" "$PY" - <<'PY' >/dev/null 2>&1
import ctypes, os
p = os.path.join(os.environ['OQS_INSTALL_PATH'], 'lib', 'liboqs.so')
ctypes.CDLL(p)
PY
  then
    OQS_OK=1
  fi
fi

if [ "$OQS_OK" -ne 1 ]; then
  WORK="$(mktemp -d "$HOME/.naza-oqs-build.XXXXXX")"
  trap 'rm -rf "${WORK:-}"' EXIT
  cd "$WORK"
  curl --fail --show-error --location --proto '=https' --tlsv1.2 \
    "https://github.com/open-quantum-safe/liboqs/archive/refs/tags/${OQS_VERSION}.tar.gz" \
    -o liboqs.tar.gz
  verify_sha256 liboqs.tar.gz "$OQS_TARBALL_SHA256" "liboqs $OQS_VERSION archive"
  tar -xzf liboqs.tar.gz
  cd "liboqs-$OQS_VERSION"
  rm -rf build

  # RAM-saving build: only the two KEMs Naza actually uses, library only, one job.
  cmake -S . -B build -G Ninja \
    -DCMAKE_BUILD_TYPE=MinSizeRel \
    -DCMAKE_INSTALL_PREFIX="$OQS_PREFIX" \
    -DBUILD_SHARED_LIBS=ON \
    -DOQS_BUILD_ONLY_LIB=ON \
    -DOQS_DIST_BUILD=OFF \
    -DOQS_MINIMAL_BUILD='KEM_ml_kem_1024;KEM_hqc_256' \
    -DOQS_ENABLE_KEM_HQC=ON \
    -DOQS_USE_OPENSSL=ON \
    -DOQS_MEMOPT_BUILD=ON \
    -DCMAKE_C_FLAGS='-Os -g0'
  cmake --build build --parallel 1
  cmake --install build
  rm -rf "$WORK"
  WORK=""
fi

[ -f "$OQS_PREFIX/lib/liboqs.so" ] || die "minimal liboqs build did not produce $OQS_PREFIX/lib/liboqs.so"
export OQS_INSTALL_PATH="$OQS_PREFIX"
export LD_LIBRARY_PATH="$OQS_PREFIX/lib${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"

say "5/10 Install/verify pinned liboqs-python wrapper"
OQS_PY_OK=0
if OQS_INSTALL_PATH="$OQS_PREFIX" LD_LIBRARY_PATH="$OQS_PREFIX/lib" "$PY" - <<'PY' >/dev/null 2>&1
import oqs
assert oqs.__version__ == '0.12.0'
assert oqs.oqs_version() == '0.14.0'
need = {'ML-KEM-1024', 'HQC-256'}
assert need.issubset(set(oqs.get_enabled_kem_mechanisms()))
PY
then
  OQS_PY_OK=1
fi

if [ "$OQS_PY_OK" -ne 1 ]; then
  WORK="$(mktemp -d "$HOME/.naza-oqspy-build.XXXXXX")"
  trap 'rm -rf "${WORK:-}"' EXIT
  cd "$WORK"
  curl --fail --show-error --location --proto '=https' --tlsv1.2 \
    "https://github.com/open-quantum-safe/liboqs-python/archive/${OQS_PY_REF}.tar.gz" \
    -o liboqs-python.tar.gz
  verify_sha256 liboqs-python.tar.gz "$OQS_PY_SHA256" "liboqs-python archive"
  OQS_INSTALL_PATH="$OQS_PREFIX" LD_LIBRARY_PATH="$OQS_PREFIX/lib" \
    "$PY" -m pip install --no-deps --force-reinstall ./liboqs-python.tar.gz
  rm -rf "$WORK"
  WORK=""
fi

OQS_INSTALL_PATH="$OQS_PREFIX" LD_LIBRARY_PATH="$OQS_PREFIX/lib" "$PY" - <<'PY'
import oqs
assert oqs.__version__ == '0.12.0', oqs.__version__
assert oqs.oqs_version() == '0.14.0', oqs.oqs_version()
for name in ('ML-KEM-1024', 'HQC-256'):
    assert name in set(oqs.get_enabled_kem_mechanisms()), name
    with oqs.KeyEncapsulation(name) as kem:
        pk = kem.generate_keypair()
        ct, ss1 = kem.encap_secret(pk)
        ss2 = kem.decap_secret(ct)
        assert ss1 == ss2, name
        print(name + ': real round trip PASS')
PY

say "6/10 Install/repair llama-cpp-python $LLAMA_VERSION for Android"
# Never trust an existing import alone; verify version + packaged native library + Android loader.
LLAMA_OK=0
PURELIB="$($PY - <<'PY'
import sysconfig
print(sysconfig.get_paths()['purelib'])
PY
)"
LLAMA_PKG="$PURELIB/llama_cpp"
LLAMA_LIB="$LLAMA_PKG/lib"

if [ -f "$LLAMA_LIB/libllama.so" ]; then
  if LLAMA_CPP_LIB_PATH="$LLAMA_LIB" \
     LD_LIBRARY_PATH="$LLAMA_LIB:$OQS_PREFIX/lib${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}" \
     "$PY" - <<'PY' >/dev/null 2>&1
import ctypes, os
ctypes.CDLL(os.path.join(os.environ['LLAMA_CPP_LIB_PATH'], 'libllama.so'))
import llama_cpp
assert llama_cpp.__version__ == '0.3.1'
llama_cpp.llama_backend_init()
llama_cpp.llama_backend_free()
PY
  then
    LLAMA_OK=1
  fi
fi

if [ "$LLAMA_OK" -ne 1 ]; then
  "$PY" -m pip uninstall -y llama-cpp-python 2>/dev/null || true

  # Build from source on-device. One compile job limits RAM pressure.
  # OpenMP and llamafile are disabled for Android/Termux compatibility.
  export CMAKE_BUILD_PARALLEL_LEVEL=1
  export FORCE_CMAKE=1
  export CMAKE_ARGS='-DGGML_OPENMP=OFF -DGGML_LLAMAFILE=OFF -DGGML_NATIVE=OFF -DLLAMA_BUILD_TESTS=OFF -DLLAMA_BUILD_EXAMPLES=OFF -DLLAMA_BUILD_SERVER=OFF -DCMAKE_BUILD_TYPE=MinSizeRel'
  "$PY" -m pip install --no-cache-dir --no-binary=llama-cpp-python "llama-cpp-python==$LLAMA_VERSION"

  PURELIB="$($PY - <<'PY'
import sysconfig
print(sysconfig.get_paths()['purelib'])
PY
)"
  LLAMA_PKG="$PURELIB/llama_cpp"
  LLAMA_LIB="$LLAMA_PKG/lib"
fi

[ -d "$LLAMA_PKG" ] || die "llama_cpp package directory missing: $LLAMA_PKG"
[ -f "$LLAMA_LIB/libllama.so" ] || die "llama-cpp-python built, but libllama.so is missing from $LLAMA_LIB"

# Patch platform classification BEFORE importing llama_cpp. This avoids the old circular failure.
LLAMA_EXT="$LLAMA_PKG/_ctypes_extensions.py"
[ -f "$LLAMA_EXT" ] || die "llama_cpp/_ctypes_extensions.py missing"
if ! grep -q 'sys\.platform\.startswith("android")' "$LLAMA_EXT"; then
  backup_file "$LLAMA_EXT"
  "$PY" - "$LLAMA_EXT" <<'PY'
from pathlib import Path
import sys
p = Path(sys.argv[1])
s = p.read_text()
old = 'if sys.platform.startswith("linux") or sys.platform.startswith("freebsd"):'
new = 'if sys.platform.startswith("linux") or sys.platform.startswith("android") or sys.platform.startswith("freebsd"):'
if old not in s:
    raise SystemExit('ERROR: llama_cpp platform block not recognized; refusing blind patch')
p.write_text(s.replace(old, new, 1))
PY
fi

# Prove the Android dynamic linker can resolve the package-local native dependency graph.
LLAMA_CPP_LIB_PATH="$LLAMA_LIB" \
LD_LIBRARY_PATH="$LLAMA_LIB:$OQS_PREFIX/lib${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}" \
"$PY" - <<'PY'
import ctypes, os
libdir = os.environ['LLAMA_CPP_LIB_PATH']
lib = os.path.join(libdir, 'libllama.so')
ctypes.CDLL(lib)
import llama_cpp
assert llama_cpp.__version__ == '0.3.1', llama_cpp.__version__
llama_cpp.llama_backend_init()
llama_cpp.llama_backend_free()
print('llama-cpp-python 0.3.1 Android loader/import/backend: PASS')
PY

say "7/10 Install/verify cryptography"
"$PY" -m pip install --force-reinstall 'cryptography==46.0.5' 'cffi==2.1.1' 'pycparser==3.0'
LD_LIBRARY_PATH="$LLAMA_LIB:$OQS_PREFIX/lib${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}" "$PY" - <<'PY'
import os
from cryptography import __version__
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
assert __version__ == '46.0.5', __version__
k = AESGCM.generate_key(bit_length=256); n = os.urandom(12); p = b'naza-termux'
c = AESGCM(k).encrypt(n, p, None)
assert AESGCM(k).decrypt(n, c, None) == p
print('cryptography/AES-256-GCM: PASS')
PY

say "8/10 Configure Android Keystore Gate 3"
if ! "$KEYSTORE" list 2>/dev/null | grep -q '"alias"[[:space:]]*:[[:space:]]*"naza-unlock"'; then
  "$KEYSTORE" generate naza-unlock -a RSA -s 2048 -u 10
fi

"$PREFIX/bin/python" - "$KEYSTORE" <<'PY'
import json, subprocess, sys
items = json.loads(subprocess.check_output([sys.argv[1], 'list'], text=True))
for item in items:
    if item.get('alias') != 'naza-unlock':
        continue
    auth = item.get('user_authentication') or {}
    good = (
        item.get('algorithm') == 'RSA'
        and int(item.get('size', 0)) == 2048
        and bool(item.get('inside_secure_hardware'))
        and bool(auth.get('required'))
        and bool(auth.get('enforced_by_secure_hardware'))
        and int(auth.get('validity_duration_seconds', -1)) == 10
    )
    raise SystemExit(0 if good else 'naza-unlock exists but does not satisfy Gate 3 hardware policy')
raise SystemExit('naza-unlock alias missing after generation')
PY

say "9/10 Validate Naza source and launch files"
chmod 700 "$NAZA_DIR/naza_unlock.sh" "$NAZA_DIR/run_naza.sh"
"$PY" -m py_compile \
  "$NAZA_DIR/main.py" \
  "$NAZA_DIR/naza_storage.py" \
  "$NAZA_DIR/spooky_combiner.py" \
  "$NAZA_DIR/spooky_trihybrid.py" \
  "$NAZA_DIR/naza_crypto_preflight.py"
bash -n "$NAZA_DIR/naza_unlock.sh"
bash -n "$NAZA_DIR/run_naza.sh"

say "10/10 End-to-end runtime preflight in the exact launch environment"
OQS_INSTALL_PATH="$OQS_PREFIX" \
LLAMA_CPP_LIB_PATH="$LLAMA_LIB" \
LD_LIBRARY_PATH="$LLAMA_LIB:$OQS_PREFIX/lib${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}" \
LD_PRELOAD="$TERMUX_EXEC" \
NAZA_CRYPTO_MODE=tri \
NAZA_REQUIRE_PROCESS_HARDENING=1 \
"$PY" "$NAZA_DIR/naza_crypto_preflight.py"

cat <<EOF

Native Termux reconciliation complete.
Preserved application data was not intentionally rekeyed or deleted.

Verified:
  liboqs $OQS_VERSION: minimal ML-KEM-1024 + HQC-256, one-job build
  liboqs-python 0.12.0: real KEM round trips
  llama-cpp-python $LLAMA_VERSION: Android shared-library load + import + backend init
  cryptography 46.0.5: AES-256-GCM
  Android hardware-backed Keystore Gate 3
  Naza Python/shell syntax + runtime crypto/llama preflight

Next:
  bash ~/naza/naza_unlock.sh
  bash ~/naza/run_naza.sh
EOF
