#!/data/data/com.termux/files/usr/bin/bash

###############################################################################
# NAZA NATIVE TERMUX MASTER REPAIR / RECONCILIATION INSTALLER
#
# Target:
#   Native Google Play Termux
#   Android 15 / API 35
#   aarch64 / arm64-v8a
#
# PURPOSE
# -------
# This is a repair/reconciliation installer, NOT a clean-install script.
#
# It discovers existing components first.
#
# It will:
#
#   - preserve existing Naza data
#   - preserve .enc_key
#   - preserve encrypted history
#   - preserve models
#   - discover existing liboqs installations
#   - validate liboqs before building anything
#   - reuse working liboqs 0.14.0
#   - repair liboqs only when actually missing/broken
#   - discover/reuse liboqs-python 0.12.0
#   - repair llama-cpp-python Android support
#   - repair cryptography without libpython LD_PRELOAD
#   - install missing application dependencies
#   - configure native Termux launchers
#   - remove PRoot runtime usage
#   - remove termux-fingerprint runtime usage
#   - configure Android Keystore Gate 3 correctly
#   - repair a bad naza-unlock key
#   - preserve the existing NKEY4/token protocol
#   - validate every Python file
#   - validate every shell file
#   - test ML-KEM-1024
#   - test HQC-256
#   - test X25519
#   - test AES-256-GCM
#   - test process hardening
#
# IMPORTANT
# ---------
# This script NEVER automatically rekeys Naza.
#
# It will NEVER intentionally delete:
#
#   .enc_key
#   chat_history.db.aes
#   chat_history.db.aes.mac
#   models/
#   .naza-private-tmp/
#
# The only Keystore key it may delete/recreate is:
#
#   naza-unlock
#
# and only if its Gate 3 authorization policy is wrong.
#
###############################################################################

set -Eeuo pipefail
IFS=$'\n\t'
umask 077

###############################################################################
# BASIC ENVIRONMENT
###############################################################################

PREFIX="${PREFIX:-/data/data/com.termux/files/usr}"
HOME="${HOME:-/data/data/com.termux/files/home}"

NAZA_DIR="${NAZA_DIR:-$HOME/naza}"
VENV="$NAZA_DIR/venv-termux"

TERMUX_EXEC="$PREFIX/lib/libtermux-exec.so"
KEYSTORE="$PREFIX/bin/termux-keystore"

OQS_VERSION="0.14.0"
OQS_HOME="$HOME/.local/liboqs-$OQS_VERSION"
OQS_SRC="$HOME/liboqs-$OQS_VERSION"

OQS_PY_VERSION="0.12.0"
CRYPTO_VERSION="46.0.5"
LLAMA_VERSION="0.3.1"

BACKUP_ROOT="$HOME/.naza-native-backups"
STAMP="$(date +%Y%m%d-%H%M%S)"
BACKUP_DIR="$BACKUP_ROOT/$STAMP"

LOG="$NAZA_DIR/.naza-native-repair.log"
LOCK="$NAZA_DIR/.naza-native-repair.lock"

###############################################################################
# TERMUX EXECUTION HOOK
#
# This is REQUIRED for native Termux executable compatibility.
#
# Absolutely NO libpython preload.
###############################################################################

export LD_PRELOAD="$TERMUX_EXEC"
export PYTHONUNBUFFERED=1
export PIP_DISABLE_PIP_VERSION_CHECK=1

###############################################################################
# LOGGING
###############################################################################

mkdir -p "$NAZA_DIR"
chmod 700 "$NAZA_DIR"

touch "$LOG"
chmod 600 "$LOG"

exec > >(tee -a "$LOG") 2>&1

###############################################################################
# FUNCTIONS
###############################################################################

die() {
    echo
    echo "================================================================"
    echo " NAZA REPAIR STOPPED"
    echo "================================================================"
    echo
    echo "ERROR: $*"
    echo
    echo "Existing Naza data was not intentionally rekeyed."
    echo
    exit 1
}

warn() {
    echo "WARNING: $*" >&2
}

section() {
    echo
    echo "================================================================"
    echo " $*"
    echo "================================================================"
}

have() {
    command -v "$1" >/dev/null 2>&1
}

backup_file() {
    local src="$1"
    local rel

    [ -e "$src" ] || return 0

    case "$src" in
        "$NAZA_DIR"/*)
            rel="${src#$NAZA_DIR/}"
            ;;
        *)
            rel="$(basename "$src")"
            ;;
    esac

    mkdir -p "$BACKUP_DIR/$(dirname "$rel")"
    cp -a "$src" "$BACKUP_DIR/$rel"
}

###############################################################################
# LOCK
###############################################################################

if [ -e "$LOCK" ]; then
    die "Repair installer lock already exists:

$LOCK

If no installer is running, remove that file manually."
fi

printf '%s\n' "$$" > "$LOCK"
trap 'rm -f "$LOCK"' EXIT

###############################################################################
# BASIC CHECK
###############################################################################

section "1. NATIVE TERMUX ENVIRONMENT"

[ -d "$PREFIX" ] ||
    die "PREFIX does not exist: $PREFIX"

[ -d "$NAZA_DIR" ] ||
    die "Naza directory does not exist: $NAZA_DIR"

[ -f "$NAZA_DIR/main.py" ] ||
    die "main.py not found: $NAZA_DIR/main.py"

[ -x "$TERMUX_EXEC" ] ||
    die "Termux execution hook missing:
$TERMUX_EXEC"

ANDROID_API="$(getprop ro.build.version.sdk 2>/dev/null || true)"
ANDROID_ABI="$(getprop ro.product.cpu.abi 2>/dev/null || true)"

echo "PREFIX:      $PREFIX"
echo "Naza:        $NAZA_DIR"
echo "Android API: ${ANDROID_API:-unknown}"
echo "Android ABI: ${ANDROID_ABI:-unknown}"

if [ -n "$ANDROID_API" ] && [ "$ANDROID_API" -lt 30 ]; then
    die "Android API 30+ required."
fi

if [ -n "$ANDROID_ABI" ] &&
   [ "$ANDROID_ABI" != "arm64-v8a" ]; then
    warn "Expected arm64-v8a; found $ANDROID_ABI"
fi

###############################################################################
# NO PROOT
###############################################################################

section "2. VERIFYING NATIVE EXECUTION"

if pgrep -af '(^|/)(proot|proot-distro)( |$)' >/dev/null 2>&1; then
    die "A PRoot process is currently running."
fi

echo "PRoot runtime: NONE"

###############################################################################
# BACKUP
###############################################################################

section "3. BACKING UP SOURCE BEFORE REPAIR"

mkdir -p "$BACKUP_DIR"
chmod 700 "$BACKUP_DIR"

find "$NAZA_DIR" \
    -maxdepth 4 \
    -type f \
    \( \
        -name '*.py' \
        -o -name '*.sh' \
        -o -name '*.bash' \
        -o -name 'requirements*.txt' \
        -o -name 'pyproject.toml' \
        -o -name 'setup.py' \
    \) \
    ! -path "$VENV/*" \
    ! -path '*/.git/*' \
    ! -path '*/models/*' \
    -print0 |
while IFS= read -r -d '' f; do
    backup_file "$f"
done

echo "Backup:"
echo "  $BACKUP_DIR"

###############################################################################
# PRIVATE DATA PRESERVATION
###############################################################################

section "4. PRIVATE DATA PRESERVATION CHECK"

for f in \
    "$NAZA_DIR/.enc_key" \
    "$NAZA_DIR/chat_history.db.aes" \
    "$NAZA_DIR/chat_history.db.aes.mac" \
    "$NAZA_DIR/pq_pubkey.b64" \
    "$NAZA_DIR/naza.lock.json"
do

    if [ -e "$f" ]; then
        echo "PRESERVE: $f"
    else
        echo "ABSENT:   $f"
    fi

done

for d in \
    "$NAZA_DIR/models" \
    "$NAZA_DIR/.naza-private-tmp"
do

    if [ -d "$d" ]; then
        echo "PRESERVE: $d"
    else
        echo "ABSENT:   $d"
    fi

done

###############################################################################
# TERMUX PACKAGES
###############################################################################

section "5. TERMUX PACKAGE RECONCILIATION"

pkg update

pkg install -y \
    python \
    python-pip \
    git \
    curl \
    cmake \
    make \
    clang \
    pkg-config \
    openssl \
    libandroid-support \
    rust \
    binutils \
    coreutils \
    findutils \
    grep \
    sed \
    tar \
    gzip \
    unzip \
    termux-api

[ -x "$KEYSTORE" ] ||
    die "termux-keystore unavailable after termux-api installation."

echo "Termux packages: PASS"

###############################################################################
# PYTHON VENV DISCOVERY
###############################################################################

section "6. PYTHON VENV DISCOVERY / REPAIR"

if [ -x "$VENV/bin/python" ]; then
    echo "Existing venv found:"
    echo "  $VENV"
else
    echo "Creating native Termux venv:"
    echo "  $VENV"

    python -m venv "$VENV"
fi

PYTHON_BIN="$VENV/bin/python"

[ -x "$PYTHON_BIN" ] ||
    die "Python venv is unavailable."

"$PYTHON_BIN" --version

"$PYTHON_BIN" -m pip install \
    --upgrade \
    pip \
    setuptools \
    wheel

###############################################################################
# REQUIREMENTS
###############################################################################

section "7. TERMUX REQUIREMENTS RECONCILIATION"

TERMUX_REQ="$NAZA_DIR/requirements-termux-final.txt"

if [ ! -f "$TERMUX_REQ" ]; then

    backup_file "$TERMUX_REQ"

    cat > "$TERMUX_REQ" <<'REQ'
# Native Google Play Termux Naza dependencies.
#
# Android-incompatible packages intentionally omitted:
#
#   psutil
#   rustworkx
#   scipy
#   scipy-openblas32
#   pennylane
#   pennylane-lightning

httpx==0.28.1
aiosqlite==0.22.1

llama-cpp-python==0.3.1
numpy==2.5.3
MarkupSafe==3.0.3
diskcache==5.6.3
Jinja2==3.1.6
typing-extensions==4.16.0

cryptography==46.0.5
cffi==2.1.1
pycparser==3.0
REQ

    chmod 600 "$TERMUX_REQ"

else

    echo "Existing requirements file found:"
    echo "  $TERMUX_REQ"

fi

###############################################################################
# INSTALL BASIC PYTHON DEPS
###############################################################################

"$PYTHON_BIN" -m pip install \
    "httpx==0.28.1" \
    "aiosqlite==0.22.1" \
    "numpy==2.5.3" \
    "MarkupSafe==3.0.3" \
    "diskcache==5.6.3" \
    "Jinja2==3.1.6" \
    "typing-extensions==4.16.0"

###############################################################################
# LIBOQS DISCOVERY
#
# THIS IS THE IMPORTANT REPAIR.
#
# We do not assume that "missing from preferred path" means missing.
###############################################################################

section "8. DISCOVERING EXISTING LIBOQS"

find_existing_oqs() {

    local candidate

    # Preferred installation.
    for candidate in \
        "$HOME/.local/liboqs-0.14.0/lib/liboqs.so" \
        "$HOME/.local/liboqs-0.14.0/lib/liboqs.so.0" \
        "$HOME/.local/lib/liboqs.so" \
        "$PREFIX/lib/liboqs.so"
    do

        if [ -f "$candidate" ]; then
            printf '%s\n' "$candidate"
            return 0
        fi

    done

    # Search common user-local locations.
    while IFS= read -r -d '' candidate; do

        case "$candidate" in
            "$VENV"/*)
                continue
                ;;
        esac

        printf '%s\n' "$candidate"
        return 0

    done < <(
        find \
            "$HOME/.local" \
            "$HOME/local" \
            "$PREFIX/lib" \
            -type f \
            \( \
                -name 'liboqs.so' \
                -o -name 'liboqs.so.0' \
                -o -name 'liboqs.so.*' \
            \) \
            -print0 \
            2>/dev/null
    )

    return 1
}

OQS_LIB_DISCOVERED=""

if OQS_LIB_DISCOVERED="$(find_existing_oqs)"; then

    echo "Existing liboqs discovered:"
    echo "  $OQS_LIB_DISCOVERED"

else

    echo "No usable liboqs library discovered."

fi

###############################################################################
# LIBOQS VALIDATION
###############################################################################

validate_oqs() {

    local library="$1"

    [ -f "$library" ] || return 1

    OQS_TEST_LIB="$library" \
    "$PYTHON_BIN" - <<'PY'
import ctypes
import os
import sys

path = os.environ["OQS_TEST_LIB"]

try:
    lib = ctypes.CDLL(path)
except OSError as e:
    print("CDLL failure:", e)
    raise SystemExit(1)

try:
    lib.OQS_version.restype = ctypes.c_char_p
    version = lib.OQS_version().decode()
except Exception as e:
    print("OQS_version failure:", e)
    raise SystemExit(1)

print("Detected liboqs:", version)

if not version.startswith("0.14.0"):
    print("Wrong liboqs version")
    raise SystemExit(2)

for symbol in (
    "OQS_KEM_ml_kem_1024_new",
    "OQS_KEM_hqc_256_new",
):

    if not hasattr(lib, symbol):
        print("Missing:", symbol)
        raise SystemExit(3)

    print("Found:", symbol)

print("liboqs validation: PASS")
PY
}

###############################################################################
# NORMALIZE OQS PREFIX
###############################################################################

if [ -n "$OQS_LIB_DISCOVERED" ]; then

    OQS_DETECTED_LIB_DIR="$(dirname "$OQS_LIB_DISCOVERED")"

    OQS_DETECTED_PREFIX="$(dirname "$OQS_DETECTED_LIB_DIR")"

    export OQS_INSTALL_PATH="$OQS_DETECTED_PREFIX"
    export LD_LIBRARY_PATH="$OQS_DETECTED_LIB_DIR${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"

    echo "Detected OQS prefix:"
    echo "  $OQS_INSTALL_PATH"

fi

###############################################################################
# IF EXISTING OQS IS VALID, DO NOT BUILD
###############################################################################

if [ -n "$OQS_LIB_DISCOVERED" ] &&
   validate_oqs "$OQS_LIB_DISCOVERED"
then

    echo
    echo "Existing liboqs is GOOD."
    echo "No rebuild required."

    # Normalize canonical variables.
    OQS_HOME="$(dirname "$(dirname "$OQS_LIB_DISCOVERED")")"
    OQS_LIB="$OQS_LIB_DISCOVERED"

else

    section "9. REPAIRING LIBOQS 0.14.0"

    echo "A valid liboqs 0.14.0 installation was not found."
    echo "Only now will a build be attempted."

    if [ ! -d "$OQS_SRC/.git" ]; then

        rm -rf "$OQS_SRC"

        git clone \
            --depth 1 \
            --branch 0.14.0 \
            --single-branch \
            https://github.com/open-quantum-safe/liboqs.git \
            "$OQS_SRC"

    fi

    cd "$OQS_SRC"

    TAG="$(
        git describe \
            --tags \
            --exact-match \
            HEAD \
            2>/dev/null || true
    )"

    if [ "$TAG" != "$OQS_VERSION" ]; then

        git fetch \
            --depth 1 \
            origin \
            "refs/tags/$OQS_VERSION:refs/tags/$OQS_VERSION"

        git checkout "$OQS_VERSION"

    fi

    TAG="$(
        git describe \
            --tags \
            --exact-match \
            HEAD \
            2>/dev/null || true
    )"

    [ "$TAG" = "$OQS_VERSION" ] ||
        die "liboqs source is not tag $OQS_VERSION."

    rm -rf build

    cmake -S . -B build \
        -G "Unix Makefiles" \
        -DCMAKE_BUILD_TYPE=MinSizeRel \
        -DCMAKE_INSTALL_PREFIX="$OQS_HOME" \
        -DBUILD_SHARED_LIBS=ON \
        -DOQS_BUILD_ONLY_LIB=ON \
        -DOQS_DIST_BUILD=OFF \
        -DOQS_MINIMAL_BUILD="KEM_ml_kem_1024;KEM_hqc_256" \
        -DOQS_ENABLE_KEM_HQC=ON \
        -DOQS_USE_OPENSSL=ON \
        -DOQS_MEMOPT_BUILD=ON \
        -DCMAKE_C_FLAGS="-Os -g0"

    cmake --build build --parallel 1

    cmake --install build

    OQS_LIB="$OQS_HOME/lib/liboqs.so"

    [ -f "$OQS_LIB" ] ||
        die "liboqs build completed but library is missing."

    export OQS_INSTALL_PATH="$OQS_HOME"
    export LD_LIBRARY_PATH="$OQS_HOME/lib${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"

    validate_oqs "$OQS_LIB" ||
        die "New liboqs installation failed validation."

fi

###############################################################################
# FINAL OQS NORMALIZATION
###############################################################################

export OQS_INSTALL_PATH="$OQS_HOME"

if [ ! -f "$OQS_HOME/lib/liboqs.so" ]; then

    # Existing valid installation may have been found under another prefix.
    # Create a compatibility symlink only when safe.
    mkdir -p "$OQS_HOME/lib"

    if [ -n "${OQS_LIB:-}" ] &&
       [ -f "$OQS_LIB" ]; then

        ln -sf "$OQS_LIB" "$OQS_HOME/lib/liboqs.so"

    fi

fi

if [ -f "$OQS_HOME/lib/liboqs.so" ]; then
    OQS_LIB="$OQS_HOME/lib/liboqs.so"
else
    OQS_LIB="${OQS_LIB:-}"
fi

[ -n "$OQS_LIB" ] ||
    die "Could not establish a usable liboqs library."

export LD_LIBRARY_PATH="$(
    dirname "$OQS_LIB"
)${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"

###############################################################################
# LIBOQS PYTHON
###############################################################################

section "10. LIBOQS-PYTHON 0.12.0 DISCOVERY"

OQS_PY_VERSION_FOUND="$(
    OQS_INSTALL_PATH="$OQS_INSTALL_PATH" \
    "$PYTHON_BIN" - <<'PY' 2>/dev/null || true
import oqs
print(oqs.__version__)
PY
)"

if [ "$OQS_PY_VERSION_FOUND" = "$OQS_PY_VERSION" ]; then

    echo "liboqs-python 0.12.0 already installed."

else

    echo "Installing/reparing liboqs-python 0.12.0."

    TMP_OQS_PY="$(
        mktemp -d
    )"

    trap '
        rm -rf "${TMP_OQS_PY:-}"
        rm -f "$LOCK"
    ' EXIT

    git clone \
        --depth 1 \
        --branch 0.12.0 \
        --single-branch \
        https://github.com/open-quantum-safe/liboqs-python.git \
        "$TMP_OQS_PY/liboqs-python"

    cd "$TMP_OQS_PY/liboqs-python"

    OQS_PY_ACTUAL_COMMIT="$(
        git rev-parse HEAD
    )"

    echo "liboqs-python commit:"
    echo "  $OQS_PY_ACTUAL_COMMIT"

    "$PYTHON_BIN" -m pip uninstall -y \
        liboqs-python \
        oqs \
        2>/dev/null || true

    export OQS_INSTALL_PATH="$OQS_HOME"
    export LD_LIBRARY_PATH="$OQS_HOME/lib${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"

    "$PYTHON_BIN" -m pip install \
        --no-deps \
        .

    rm -rf "$TMP_OQS_PY"
    TMP_OQS_PY=""
fi

###############################################################################
# OQS PYTHON FUNCTIONAL TEST
###############################################################################

section "11. TESTING LIBOQS-PYTHON"

export OQS_INSTALL_PATH="$OQS_HOME"
export LD_LIBRARY_PATH="$OQS_HOME/lib${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"

"$PYTHON_BIN" - <<'PY'
import oqs

print("liboqs-python:", oqs.__version__)

if oqs.__version__ != "0.12.0":
    raise SystemExit("Expected liboqs-python 0.12.0")

mechs = set(
    oqs.get_enabled_kem_mechanisms()
)

for name in (
    "ML-KEM-1024",
    "HQC-256",
):

    if name not in mechs:
        raise SystemExit(
            "Missing required KEM: " + name
        )

    print(name + ": ENABLED")
PY

###############################################################################
# REAL KEM ROUND TRIPS
###############################################################################

section "12. KEM ROUND-TRIP TESTS"

"$PYTHON_BIN" - <<'PY'
import oqs

for name in (
    "ML-KEM-1024",
    "HQC-256",
):

    print("Testing:", name)

    with oqs.KeyEncapsulation(name) as kem:

        public_key = kem.generate_keypair()

        ciphertext, sender_secret = \
            kem.encap_secret(public_key)

        receiver_secret = \
            kem.decap_secret(ciphertext)

        if sender_secret != receiver_secret:
            raise SystemExit(
                name + " shared secret mismatch"
            )

    print(name + ": PASS")
PY

###############################################################################
# LLAMA CPP DISCOVERY / ANDROID-SAFE SOURCE BUILD
###############################################################################

section "13. LLAMA-CPP-PYTHON DISCOVERY / REPAIR"

LLAMA_PURELIB="$($PYTHON_BIN - <<'PY'
import sysconfig
print(sysconfig.get_paths()["purelib"])
PY
)"
LLAMA_PKG_DIR="$LLAMA_PURELIB/llama_cpp"
LLAMA_LIB_DIR="$(find "$LLAMA_PKG_DIR" -type f -name 'libllama.so*' -print -quit 2>/dev/null | xargs -r dirname)"

llama_works() {
    [ -n "${LLAMA_LIB_DIR:-}" ] || return 1
    [ -f "$LLAMA_LIB_DIR/libllama.so" ] || return 1
    LLAMA_CPP_LIB_PATH="$LLAMA_LIB_DIR" \
    LD_LIBRARY_PATH="$LLAMA_LIB_DIR:$OQS_HOME/lib${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}" \
    "$PYTHON_BIN" - <<'PY' >/dev/null 2>&1
import importlib.metadata as md
assert md.version("llama-cpp-python") == "0.3.1"
import llama_cpp
from llama_cpp import Llama
assert callable(Llama)
PY
}

if llama_works; then
    echo "llama-cpp-python $LLAMA_VERSION native Android load: PASS"
else
    echo "Rebuilding llama-cpp-python $LLAMA_VERSION from source for native Termux."
    "$PYTHON_BIN" -m pip uninstall -y llama-cpp-python 2>/dev/null || true
    export CMAKE_BUILD_PARALLEL_LEVEL=1
    export FORCE_CMAKE=1
    export CMAKE_ARGS="-DCMAKE_BUILD_TYPE=MinSizeRel -DBUILD_SHARED_LIBS=ON -DGGML_NATIVE=OFF -DGGML_OPENMP=OFF -DGGML_BUILD_TESTS=OFF -DGGML_BUILD_EXAMPLES=OFF"
    "$PYTHON_BIN" -m pip install \
        --no-cache-dir \
        --no-binary llama-cpp-python \
        --no-deps \
        --force-reinstall \
        "llama-cpp-python==$LLAMA_VERSION"

    LLAMA_PKG_DIR="$LLAMA_PURELIB/llama_cpp"
    LLAMA_EXT="$LLAMA_PKG_DIR/_ctypes_extensions.py"
    [ -f "$LLAMA_EXT" ] || die "Could not find llama_cpp/_ctypes_extensions.py after source build."

    # Patch 0.3.1 loader classification without importing llama_cpp first.
    if ! grep -q 'sys\.platform\.startswith("android")' "$LLAMA_EXT"; then
        backup_file "$LLAMA_EXT"
        "$PYTHON_BIN" - "$LLAMA_EXT" <<'PY'
from pathlib import Path
import sys
p = Path(sys.argv[1])
s = p.read_text()
old = 'if sys.platform.startswith("linux") or sys.platform.startswith("freebsd"):'
new = 'if sys.platform.startswith("linux") or sys.platform.startswith("android") or sys.platform.startswith("freebsd"):'
if old in s:
    p.write_text(s.replace(old, new, 1))
PY
    fi

    LLAMA_LIB_DIR="$(find "$LLAMA_PKG_DIR" -type f -name 'libllama.so*' -print -quit 2>/dev/null | xargs -r dirname)"
    [ -n "$LLAMA_LIB_DIR" ] || die "llama-cpp-python installed but libllama.so was not packaged."

    # Prove Android's dynamic loader can resolve the installed native library.
    LLAMA_CPP_LIB_PATH="$LLAMA_LIB_DIR" \
    LD_LIBRARY_PATH="$LLAMA_LIB_DIR:$OQS_HOME/lib${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}" \
    "$PYTHON_BIN" - "$LLAMA_LIB_DIR/libllama.so" <<'PY'
import ctypes, sys
ctypes.CDLL(sys.argv[1], mode=getattr(ctypes, "RTLD_GLOBAL", 0))
import llama_cpp
from llama_cpp import Llama
print("llama-cpp-python:", llama_cpp.__version__)
print("libllama load + Python API: PASS")
PY
fi

export LLAMA_CPP_LIB_PATH="$LLAMA_LIB_DIR"
export LD_LIBRARY_PATH="$LLAMA_LIB_DIR:$OQS_HOME/lib${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"

###############################################################################
# CRYPTOGRAPHY
###############################################################################

section "14. CRYPTOGRAPHY DISCOVERY / REPAIR"

CRYPTO_WORKING=0

if "$PYTHON_BIN" - <<'PY'
import os

from cryptography import __version__

if __version__ != "46.0.5":
    raise SystemExit(1)

if "libpython" in os.environ.get("LD_PRELOAD", ""):
    raise SystemExit(
        "libpython preload detected"
    )

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

key = AESGCM.generate_key(
    bit_length=256
)

nonce = os.urandom(12)

message = b"NAZA-CRYPTO-REPAIR"

ciphertext = AESGCM(key).encrypt(
    nonce,
    message,
    None,
)

plaintext = AESGCM(key).decrypt(
    nonce,
    ciphertext,
    None,
)

if plaintext != message:
    raise SystemExit(1)

print("Existing cryptography is working.")
PY
then

    CRYPTO_WORKING=1

fi

if [ "$CRYPTO_WORKING" -eq 0 ]; then

    echo "Repairing cryptography."

    "$PYTHON_BIN" -m pip install \
        --force-reinstall \
        "cryptography==$CRYPTO_VERSION" \
        "cffi==2.1.1" \
        "pycparser==3.0"

fi

###############################################################################
# CRYPTO FINAL
###############################################################################

"$PYTHON_BIN" - <<'PY'
import os

from cryptography import __version__
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

print("cryptography:", __version__)

if __version__ != "46.0.5":
    raise SystemExit(
        "Wrong cryptography version"
    )

preload = os.environ.get("LD_PRELOAD", "")

if "libpython" in preload:
    raise SystemExit(
        "SECURITY FAILURE: libpython preload present"
    )

key = AESGCM.generate_key(
    bit_length=256
)

nonce = os.urandom(12)

plaintext = b"NAZA-AES-256-GCM"

ciphertext = AESGCM(key).encrypt(
    nonce,
    plaintext,
    b"NAZA",
)

recovered = AESGCM(key).decrypt(
    nonce,
    ciphertext,
    b"NAZA",
)

if recovered != plaintext:
    raise SystemExit(
        "AES-GCM verification failed"
    )

print("AES-256-GCM: PASS")
print("libpython preload: NONE")
PY

###############################################################################
# GATE 3 HELPERS
###############################################################################

section "15. ANDROID KEYSTORE GATE 3 RECONCILIATION"

[ -x "$KEYSTORE" ] ||
    die "termux-keystore missing."

keystore_state() {

    "$PREFIX/bin/python" - "$KEYSTORE" <<'PY'
import json
import subprocess
import sys

ks = sys.argv[1]

try:
    raw = subprocess.check_output(
        [ks, "list"],
        text=True,
        stderr=subprocess.DEVNULL,
    )
except Exception:
    print("ERROR")
    raise SystemExit(0)

try:
    items = json.loads(raw)
except Exception:
    print("ERROR")
    raise SystemExit(0)

for item in items:

    if item.get("alias") != "naza-unlock":
        continue

    auth = item.get("user_authentication") or {}

    good = (
        item.get("algorithm") == "RSA"
        and int(item.get("size", 0)) == 2048
        and bool(
            item.get("inside_secure_hardware")
        )
        and bool(
            auth.get("required")
        )
        and bool(
            auth.get("enforced_by_secure_hardware")
        )
        and int(
            auth.get(
                "validity_duration_seconds",
                -1
            )
        ) == 10
    )

    print(
        "CORRECT"
        if good
        else
        "WRONG"
    )

    raise SystemExit(0)

print("MISSING")
PY

}

###############################################################################
# REMOVE ONLY ACCIDENTAL --help KEY
###############################################################################

if "$KEYSTORE" list 2>/dev/null |
    grep -q '"alias"[[:space:]]*:[[:space:]]*"--help"'
then

    echo "Removing accidental alias: --help"

    "$KEYSTORE" delete --help || true

fi

###############################################################################
# REPAIR NAZA-UNLOCK
###############################################################################

KEY_STATE="$(keystore_state)"

echo "naza-unlock: $KEY_STATE"

if [ "$KEY_STATE" = "WRONG" ]; then

    echo
    echo "Existing naza-unlock has an incorrect authorization policy."
    echo "Deleting ONLY naza-unlock."
    echo

    "$KEYSTORE" delete naza-unlock

    KEY_STATE="MISSING"

fi

if [ "$KEY_STATE" = "MISSING" ]; then

    echo
    echo "Generating correct Gate 3 key."
    echo
    echo "  alias:                    naza-unlock"
    echo "  algorithm:                RSA"
    echo "  size:                     2048"
    echo "  secure hardware:          required"
    echo "  user authentication:      required"
    echo "  validity:                 10 seconds"
    echo

    "$KEYSTORE" generate \
        naza-unlock \
        -a RSA \
        -s 2048 \
        -u 10

fi

KEY_STATE="$(keystore_state)"

[ "$KEY_STATE" = "CORRECT" ] ||
    die "Could not establish the required naza-unlock Gate 3 key."

echo
"$KEYSTORE" list
echo

###############################################################################
# REPAIR naza_unlock.sh
###############################################################################

section "16. REPAIRING naza_unlock.sh"

backup_file "$NAZA_DIR/naza_unlock.sh"

cat > "$NAZA_DIR/naza_unlock.sh" <<'NAZA_UNLOCK'
#!/data/data/com.termux/files/usr/bin/bash

###############################################################################
# NAZA GATE 3
#
# Native Termux Android Keystore authentication.
#
# No biometric-specific Termux API.
#
# Existing Naza token protocol:
#
#   random challenge
#   Android Keystore SHA256withRSA signature
#   SHA256(challenge + signature)
#   64 lowercase hexadecimal characters
#
###############################################################################

set -Eeuo pipefail
IFS=$'\n\t'
umask 077

PREFIX="${PREFIX:-/data/data/com.termux/files/usr}"
HOME_T="${HOME:-/data/data/com.termux/files/home}"

NAZA_DIR="$HOME_T/.naza"

KEYSTORE="$PREFIX/bin/termux-keystore"

ALIAS="naza-unlock"
SIGN_ALGO="SHA256withRSA"

CHALLENGE="$NAZA_DIR/challenge"
SIGNATURE="$NAZA_DIR/signature"
TOKEN="$NAZA_DIR/unlock.token"

export LD_PRELOAD="$PREFIX/lib/libtermux-exec.so"

die() {
    echo "ERROR: $*" >&2
    rm -f \
        "$CHALLENGE" \
        "$SIGNATURE"
    exit 1
}

###############################################################################
# DIRECTORY
###############################################################################

mkdir -p "$NAZA_DIR"

[ ! -L "$NAZA_DIR" ] ||
    die ".naza is a symbolic link"

chmod 700 "$NAZA_DIR"

###############################################################################
# KEYSTORE
###############################################################################

[ -x "$KEYSTORE" ] ||
    die "termux-keystore unavailable"

###############################################################################
# POLICY CHECK
###############################################################################

STATE="$(
    "$PREFIX/bin/python" - "$KEYSTORE" <<'PY'
import json
import subprocess
import sys

ks = sys.argv[1]

items = json.loads(
    subprocess.check_output(
        [ks, "list"],
        text=True,
    )
)

for item in items:

    if item.get("alias") != "naza-unlock":
        continue

    auth = item.get("user_authentication") or {}

    good = (
        item.get("algorithm") == "RSA"
        and int(item.get("size", 0)) == 2048
        and bool(item.get("inside_secure_hardware"))
        and bool(auth.get("required"))
        and bool(auth.get("enforced_by_secure_hardware"))
        and int(
            auth.get(
                "validity_duration_seconds",
                -1
            )
        ) == 10
    )

    print(
        "CORRECT"
        if good
        else
        "WRONG"
    )

    raise SystemExit(0)

print("MISSING")
PY
)"

[ "$STATE" = "CORRECT" ] ||
    die "naza-unlock does not have the correct Gate 3 policy"

###############################################################################
# CLEAN OLD TEMPORARY FILES
###############################################################################

rm -f \
    "$CHALLENGE" \
    "$SIGNATURE"

###############################################################################
# CREATE RANDOM CHALLENGE
###############################################################################

python - <<'PY' > "$CHALLENGE"
import secrets

print(
    secrets.token_hex(32),
    end=""
)
PY

chmod 600 "$CHALLENGE"

grep -Eq \
    '^[0-9a-f]{64}$' \
    "$CHALLENGE" ||
    die "Challenge generation failed"

###############################################################################
# USER MESSAGE
###############################################################################

echo
echo "================================================================"
echo " NAZA GATE 3"
echo "================================================================"
echo
echo "Android Keystore hardware authentication is required."
echo
echo "Lock the phone."
echo "Unlock/authenticate the phone."
echo "Then continue."
echo
echo "No biometric-specific Termux API is used."
echo

###############################################################################
# ACTUAL TERMUX-KEYSTORE SIGN INTERFACE
#
# termux-keystore:
#
#   sign <alias> <algorithm> <input-file> <output-file>
#
###############################################################################

"$KEYSTORE" sign \
    "$ALIAS" \
    "$SIGN_ALGO" \
    "$CHALLENGE" \
    "$SIGNATURE" ||
    die "Android Keystore signing failed"

[ -s "$SIGNATURE" ] ||
    die "Android Keystore returned no signature"

###############################################################################
# EXISTING NAZA TOKEN FORMAT
###############################################################################

TOKEN_VALUE="$(
    python - \
        "$CHALLENGE" \
        "$SIGNATURE" \
        <<'PY'
from pathlib import Path
import hashlib
import sys

challenge = Path(
    sys.argv[1]
).read_text().strip()

signature = Path(
    sys.argv[2]
).read_bytes()

# Naza's existing token contract:
#
# SHA256(challenge text + signature bytes)
#
# The resulting token is 64 lowercase hexadecimal characters.

digest = hashlib.sha256()

digest.update(
    challenge.encode("ascii")
)

digest.update(
    signature
)

token = digest.hexdigest()

if len(token) != 64:
    raise SystemExit(
        "Unexpected token length"
    )

print(token)
PY
)"

printf '%s\n' "$TOKEN_VALUE" |
    grep -Eq \
        '^[0-9a-f]{64}$' ||
    die "Generated token does not match Naza token format"

###############################################################################
# ATOMIC TOKEN INSTALL
###############################################################################

TMP_TOKEN="$(
    mktemp "$NAZA_DIR/.unlock.token.XXXXXX"
)"

chmod 600 "$TMP_TOKEN"

printf '%s\n' "$TOKEN_VALUE" > "$TMP_TOKEN"

mv -f \
    "$TMP_TOKEN" \
    "$TOKEN"

chmod 600 "$TOKEN"

###############################################################################
# CLEAN CHALLENGE/SIGNATURE
###############################################################################

rm -f \
    "$CHALLENGE" \
    "$SIGNATURE"

unset TOKEN_VALUE

echo
echo "Gate 3 Android Keystore authentication: PASS"
echo "Naza unlock token ready."
echo "Token: $TOKEN"
echo

NAZA_UNLOCK

chmod 700 "$NAZA_DIR/naza_unlock.sh"
bash -n "$NAZA_DIR/naza_unlock.sh"

###############################################################################
# REPAIR run_naza.sh
###############################################################################

section "17. REPAIRING NATIVE Naza LAUNCHER"

backup_file "$NAZA_DIR/run_naza.sh"

cat > "$NAZA_DIR/run_naza.sh" <<'NAZA_RUN'
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

# Keep Termux execution hook.
# NEVER use libpython preload.
export LD_PRELOAD="$PREFIX/lib/libtermux-exec.so"

[ -x "$VENV/bin/python" ] ||
    {
        echo "ERROR: native Termux Python missing." >&2
        exit 1
    }

[ -f "$OQS/lib/liboqs.so" ] ||
    {
        echo "ERROR: native liboqs missing:
$OQS/lib/liboqs.so" >&2
        exit 1
    }

export VIRTUAL_ENV="$VENV"
export PATH="$VENV/bin:$PATH"

unset PYTHONHOME
unset PYTHONPATH
unset PYTHONSTARTUP
unset PYTHONINSPECT

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

export NAZA_CRYPTO_MODE="tri"
export NAZA_REQUIRE_PROCESS_HARDENING=1
export PYTHONUNBUFFERED=1

ulimit -c 0 2>/dev/null || true

cd "$NAZA_DIR"

# Native crypto preflight.
"$VENV/bin/python" \
    "$NAZA_DIR/naza_crypto_preflight.py"

exec "$VENV/bin/python" \
    -u \
    "$NAZA_DIR/main.py" \
    "$@"

NAZA_RUN

chmod 700 "$NAZA_DIR/run_naza.sh"
bash -n "$NAZA_DIR/run_naza.sh"

###############################################################################
# REPAIR BOOT SCRIPT
###############################################################################

section "18. REPAIRING NATIVE BOOT SCRIPT"

BOOT="$NAZA_DIR/naza-termux-boot.sh"

backup_file "$BOOT"

cat > "$BOOT" <<'NAZA_BOOT'
#!/data/data/com.termux/files/usr/bin/bash

set -Eeuo pipefail
IFS=$'\n\t'
umask 077

PREFIX="${PREFIX:-/data/data/com.termux/files/usr}"
HOME="${HOME:-/data/data/com.termux/files/home}"

export LD_PRELOAD="$PREFIX/lib/libtermux-exec.so"

NAZA_DIR="$HOME/naza"

UNLOCK="$NAZA_DIR/naza_unlock.sh"
RUN="$NAZA_DIR/run_naza.sh"

[ -x "$UNLOCK" ] ||
    {
        echo "ERROR: Gate 3 helper missing." >&2
        exit 1
    }

[ -x "$RUN" ] ||
    {
        echo "ERROR: native launcher missing." >&2
        exit 1
    }

while true; do

    clear || true

    cat <<'MENU'

╔══════════════════════════════════════════╗
║              NAZA SECURITY               ║
╠══════════════════════════════════════════╣
║                                          ║
║       🔒  ANDROID KEYSTORE               ║
║                                          ║
║  Gate 3 uses the hardware-backed         ║
║  Android Keystore authorization key.     ║
║                                          ║
║  Lock phone.                             ║
║  Unlock/authenticate phone.              ║
║                                          ║
║  U  = UNLOCK / START NAZA                ║
║  L  = LOCK / EXIT                        ║
║  Q  = QUIT TO SHELL                      ║
╚══════════════════════════════════════════╝

MENU

    printf "Select [U/L/Q]: "

    IFS= read -r answer || exit 0

    case "$answer" in

        U|u)

            if "$UNLOCK"; then

                echo
                echo "Gate 3: PASS"
                echo
                echo "Starting Naza..."
                echo

                exec "$RUN"

            else

                echo
                echo "Gate 3 failed."
                echo "Authenticate the phone and try again."
                echo

                read -r -p "Press Enter..."

            fi

            ;;

        L|l)

            echo
            echo "NAZA LOCKED."
            exit 0
            ;;

        Q|q)

            exit 0
            ;;

        *)

            echo
            echo "Invalid selection."
            ;;

    esac

done

NAZA_BOOT

chmod 700 "$BOOT"
bash -n "$BOOT"

###############################################################################
# REPAIR ~/.naza_boot.sh
###############################################################################

section "19. REPAIRING USER BOOT ENTRY"

USER_BOOT="$HOME/.naza_boot.sh"

backup_file "$USER_BOOT"

cat > "$USER_BOOT" <<'NAZA_USER_BOOT'
#!/data/data/com.termux/files/usr/bin/bash

set -Eeuo pipefail
IFS=$'\n\t'

PREFIX="${PREFIX:-/data/data/com.termux/files/usr}"

export LD_PRELOAD="$PREFIX/lib/libtermux-exec.so"

exec "$HOME/naza/naza-termux-boot.sh"

NAZA_USER_BOOT

chmod 700 "$USER_BOOT"

###############################################################################
# BASHRC
###############################################################################

section "20. REPAIRING .bashrc AUTOBOOT"

BASHRC="$HOME/.bashrc"

touch "$BASHRC"

if grep -q \
    '# >>> NAZA NATIVE SECURE BOOT >>>' \
    "$BASHRC"
then

    echo "Existing native secure boot block found."

else

    cat >> "$BASHRC" <<'NAZA_BASHRC'

# >>> NAZA NATIVE SECURE BOOT >>>
#
# Native Google-Play-Termux startup.
#
# Disable for a normal shell:
#
#   export NAZA_NO_BOOT=1
#
if [ -t 0 ] && [ -t 1 ] &&
   [ -x "$HOME/naza/naza-termux-boot.sh" ]; then

    case "${NAZA_NO_BOOT:-0}" in
        1)
            ;;
        *)
            "$HOME/naza/naza-termux-boot.sh"
            ;;
    esac

fi
# <<< NAZA NATIVE SECURE BOOT <<<
NAZA_BASHRC

fi

###############################################################################
# TERMUX AUTOINSTALL SETUP
###############################################################################

section "21. REPAIRING TERMUX setup.sh"

TERMUX_SETUP="$NAZA_DIR/termux-naza-autosetup/setup.sh"

if [ -f "$TERMUX_SETUP" ]; then
    backup_file "$TERMUX_SETUP"
fi

mkdir -p "$(dirname "$TERMUX_SETUP")"

cat > "$TERMUX_SETUP" <<'NAZA_SETUP'
#!/data/data/com.termux/files/usr/bin/bash

set -Eeuo pipefail
IFS=$'\n\t'

PREFIX="${PREFIX:-/data/data/com.termux/files/usr}"

export LD_PRELOAD="$PREFIX/lib/libtermux-exec.so"

exec bash "$HOME/naza/install-native-termux-repair.sh"

NAZA_SETUP

chmod 700 "$TERMUX_SETUP"
bash -n "$TERMUX_SETUP"

###############################################################################
# INSTALLER ITSELF
###############################################################################

section "22. INSTALLER SELF-PERMISSION"

chmod 700 \
    "$NAZA_DIR/install-native-termux-repair.sh" \
    "$NAZA_DIR/naza_orbit_sim.py"

[ -f "$NAZA_DIR/Optus-X-positioning.csv" ] || die "Missing calibrated orbit source CSV: Optus-X-positioning.csv"
[ ! -L "$NAZA_DIR/Optus-X-positioning.csv" ] || die "Refusing symbolic-link orbit source CSV"
chmod 600 "$NAZA_DIR/Optus-X-positioning.csv"

###############################################################################
# PYTHON SYNTAX — ALL REPO
###############################################################################

section "23. PYTHON SYNTAX — WHOLE REPOSITORY"

PYFAIL=0

while IFS= read -r -d '' f; do

    case "$f" in
        "$VENV"/*)
            continue
            ;;
        */.git/*)
            continue
            ;;
        */__pycache__/*)
            continue
            ;;
    esac

    echo "Checking ${f#$NAZA_DIR/}"

    if ! "$PYTHON_BIN" -m py_compile "$f"; then
        PYFAIL=1
    fi

done < <(
    find "$NAZA_DIR" \
        -type f \
        -name '*.py' \
        -print0
)

[ "$PYFAIL" -eq 0 ] ||
    die "Python syntax validation failed."

echo "Python syntax: PASS"

###############################################################################
# SHELL SYNTAX — ALL REPO
###############################################################################

section "24. SHELL SYNTAX — WHOLE REPOSITORY"

SHFAIL=0

while IFS= read -r -d '' f; do

    case "$f" in
        "$VENV"/*)
            continue
            ;;
        */.git/*)
            continue
            ;;
    esac

    echo "Checking ${f#$NAZA_DIR/}"

    if ! bash -n "$f"; then
        SHFAIL=1
    fi

done < <(
    find "$NAZA_DIR" \
        -type f \
        \( -name '*.sh' -o -name '*.bash' \) \
        -print0
)

[ "$SHFAIL" -eq 0 ] ||
    die "Shell syntax validation failed."

echo "Shell syntax: PASS"

###############################################################################
# SECURITY SCAN
###############################################################################

section "25. NATIVE TERMUX SECURITY SCAN"

BAD=0

while IFS= read -r -d '' f; do

    case "$f" in
        "$VENV"/*)
            continue
            ;;
        */.git/*)
            continue
            ;;
        */__pycache__/*)
            continue
            ;;
    esac

    if grep -nE \
        '(^|[^[:alnum:]_])proot(-distro)?([^[:alnum:]_]|$)' \
        "$f" \
        >/dev/null 2>&1
    then

        echo
        echo "PROOT REFERENCE:"
        echo "$f"

        grep -nE \
            '(^|[^[:alnum:]_])proot(-distro)?([^[:alnum:]_]|$)' \
            "$f" || true

        BAD=1

    fi

    if grep -nE \
        'termux-fingerprint' \
        "$f" \
        >/dev/null 2>&1
    then

        echo
        echo "FINGERPRINT REFERENCE:"
        echo "$f"

        grep -nE \
            'termux-fingerprint' \
            "$f" || true

        BAD=1

    fi

    if grep -nE \
        'libpython3\.[0-9]+\.so' \
        "$f" \
        >/dev/null 2>&1
    then

        echo
        echo "LIBPYTHON PRELOAD REFERENCE:"
        echo "$f"

        grep -nE \
            'libpython3\.[0-9]+\.so' \
            "$f" || true

        BAD=1

    fi

done < <(
    printf '%s\0' \
        "$NAZA_DIR/main.py" \
        "$NAZA_DIR/run_naza.sh" \
        "$NAZA_DIR/naza_unlock.sh" \
        "$NAZA_DIR/naza-termux-boot.sh"
)

[ "$BAD" -eq 0 ] ||
    die "Forbidden runtime reference detected."

echo "PRoot:              NONE"
echo "termux-fingerprint:  NONE"
echo "libpython preload:   NONE"

###############################################################################
# MAIN.PY GATE 3 CONTRACT CHECK
###############################################################################

section "26. MAIN.PY GATE 3 CONTRACT"

"$PYTHON_BIN" - "$NAZA_DIR/main.py" <<'PY'
from pathlib import Path
import re
import sys

p = Path(sys.argv[1])
s = p.read_text()

required = [
    "read_unlock_token",
    "unlock.token",
    "NKEY4",
    "KEY_FLAG_PASSPHRASE",
    "ML-KEM-1024",
    "HQC-256",
    "X25519",
    "AESGCM",
]

for marker in required:

    if marker not in s:
        raise SystemExit(
            "main.py missing expected marker: "
            + marker
        )

# Token remains a 64-character lowercase hex value.
if not re.search(
    r'fullmatch\(r"\[0-9a-f\]\{64\}"',
    s,
):
    raise SystemExit(
        "Could not verify 64-character token contract."
    )

print("Gate 3 token contract: PASS")
print("NKEY4: PASS")
print("tri-hybrid markers: PASS")
PY

###############################################################################
# EXISTING KEY INSPECTION
#
# NEVER CHANGE IT.
###############################################################################

section "27. EXISTING NKEY4 PRESERVATION CHECK"

if [ -f "$NAZA_DIR/.enc_key" ]; then

    "$PYTHON_BIN" - "$NAZA_DIR/.enc_key" <<'PY'
from pathlib import Path
import sys

p = Path(sys.argv[1])
b = p.read_bytes()

print("Existing .enc_key size:", len(b))
print("Magic:", b[:5])

if b.startswith(b"NKEY4"):

    if len(b) < 7:
        raise SystemExit(
            "NKEY4 key is too short."
        )

    print("Existing NKEY4: YES")
    print("Existing key will NOT be rekeyed.")

else:

    print(
        "Existing key is not NKEY4."
    )

    print(
        "Existing key will still NOT be rekeyed."
    )
PY

else

    echo "No existing .enc_key."
    echo "No key will be created automatically."

fi

###############################################################################
# PROCESS HARDENING
###############################################################################

section "28. PROCESS HARDENING"

"$PYTHON_BIN" - <<'PY'
import ctypes

libc = ctypes.CDLL(
    None,
    use_errno=True,
)

PR_SET_DUMPABLE = 4
PR_GET_DUMPABLE = 3
PR_SET_NO_NEW_PRIVS = 38
PR_GET_NO_NEW_PRIVS = 39

if libc.prctl(
    PR_SET_DUMPABLE,
    0,
    0,
    0,
    0,
) != 0:
    raise SystemExit(
        "PR_SET_DUMPABLE failed"
    )

if libc.prctl(
    PR_GET_DUMPABLE,
    0,
    0,
    0,
    0,
) != 0:
    raise SystemExit(
        "Process remains dumpable"
    )

if libc.prctl(
    PR_SET_NO_NEW_PRIVS,
    1,
    0,
    0,
    0,
) != 0:
    raise SystemExit(
        "PR_SET_NO_NEW_PRIVS failed"
    )

if libc.prctl(
    PR_GET_NO_NEW_PRIVS,
    0,
    0,
    0,
    0,
) != 1:
    raise SystemExit(
        "NO_NEW_PRIVS verification failed"
    )

print("non-dumpable: PASS")
print("no-new-privileges: PASS")
PY

###############################################################################
# X25519 + AES
###############################################################################

section "29. X25519 + AES-256-GCM"

"$PYTHON_BIN" - <<'PY'
import os

from cryptography.hazmat.primitives.asymmetric.x25519 import (
    X25519PrivateKey,
)

from cryptography.hazmat.primitives.ciphers.aead import (
    AESGCM,
)

a = X25519PrivateKey.generate()
b = X25519PrivateKey.generate()

sa = a.exchange(
    b.public_key()
)

sb = b.exchange(
    a.public_key()
)

if sa != sb:
    raise SystemExit(
        "X25519 mismatch"
    )

print("X25519: PASS")

key = AESGCM.generate_key(
    bit_length=256
)

nonce = os.urandom(12)

message = b"NAZA-NATIVE-TERMUX"

ciphertext = AESGCM(key).encrypt(
    nonce,
    message,
    b"NKEY4",
)

plaintext = AESGCM(key).decrypt(
    nonce,
    ciphertext,
    b"NKEY4",
)

if plaintext != message:
    raise SystemExit(
        "AES-GCM mismatch"
    )

print("AES-256-GCM: PASS")
PY

###############################################################################
# REAL TRI-HYBRID CRYPTO
###############################################################################

section "30. TRI-HYBRID CRYPTO VALIDATION"

"$PYTHON_BIN" - <<'PY'
import os
import oqs

from cryptography.hazmat.primitives.asymmetric.x25519 import (
    X25519PrivateKey,
)

from cryptography.hazmat.primitives.ciphers.aead import (
    AESGCM,
)

from cryptography.hazmat.primitives.kdf.hkdf import (
    HKDF,
)

from cryptography.hazmat.primitives import hashes

###############################################################################
# ML-KEM
###############################################################################

with oqs.KeyEncapsulation(
    "ML-KEM-1024"
) as kem:

    public = kem.generate_keypair()

    ciphertext, s1 = \
        kem.encap_secret(public)

    s2 = \
        kem.decap_secret(ciphertext)

if s1 != s2:
    raise SystemExit(
        "ML-KEM-1024 failed"
    )

print("ML-KEM-1024: PASS")

###############################################################################
# HQC
###############################################################################

with oqs.KeyEncapsulation(
    "HQC-256"
) as kem:

    public = kem.generate_keypair()

    ciphertext, s3 = \
        kem.encap_secret(public)

    s4 = \
        kem.decap_secret(ciphertext)

if s3 != s4:
    raise SystemExit(
        "HQC-256 failed"
    )

print("HQC-256: PASS")

###############################################################################
# X25519
###############################################################################

x1 = X25519PrivateKey.generate()
x2 = X25519PrivateKey.generate()

x = x1.exchange(
    x2.public_key()
)

x_check = x2.exchange(
    x1.public_key()
)

if x != x_check:
    raise SystemExit(
        "X25519 failed"
    )

print("X25519: PASS")

###############################################################################
# COMBINE
###############################################################################

root = HKDF(
    algorithm=hashes.SHA512(),
    length=32,
    salt=os.urandom(32),
    info=b"naza-tri-hybrid-repair",
).derive(
    s1 +
    s3 +
    x
)

if len(root) != 32:
    raise SystemExit(
        "Invalid derived key length"
    )

print("HKDF-SHA512: PASS")

###############################################################################
# AES
###############################################################################

nonce = os.urandom(12)

plaintext = (
    b"SpookyNaza tri-hybrid: "
    b"ML-KEM-1024 + HQC-256 + X25519"
)

ciphertext = AESGCM(root).encrypt(
    nonce,
    plaintext,
    b"NKEY4",
)

recovered = AESGCM(root).decrypt(
    nonce,
    ciphertext,
    b"NKEY4",
)

if recovered != plaintext:
    raise SystemExit(
        "AES-256-GCM failed"
    )

print("AES-256-GCM: PASS")
print()
print("TRI-HYBRID CRYPTO: PASS")
PY

###############################################################################
# SUPPORTING MODULE IMPORTS
###############################################################################

section "31. SUPPORTING MODULE IMPORT TEST"

cd "$NAZA_DIR"

export VIRTUAL_ENV="$VENV"
export PATH="$VENV/bin:$PATH"

unset PYTHONHOME
unset PYTHONPATH
unset PYTHONSTARTUP
unset PYTHONINSPECT

export OQS_INSTALL_PATH="$OQS_HOME"
export LLAMA_CPP_LIB_PATH="$LLAMA_LIB_DIR"
export LD_LIBRARY_PATH="$LLAMA_LIB_DIR:$OQS_HOME/lib${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"
export NAZA_OFFLINE_MODE=1
export NAZA_CRYPTO_MODE="tri"
export NAZA_REQUIRE_PROCESS_HARDENING=1
export LD_PRELOAD="$TERMUX_EXEC"

"$PYTHON_BIN" - <<'PY'
from pathlib import Path
import importlib

root = Path.cwd()

skip = {
    "main",
}

for p in sorted(root.glob("*.py")):

    name = p.stem

    if name.startswith("_"):
        continue

    if name in skip:
        continue

    print("IMPORT:", name)

    importlib.import_module(name)

print("Supporting module imports: PASS")
PY

###############################################################################
# MAIN IMPORT
###############################################################################

section "32. MAIN.PY IMPORT TEST"

"$PYTHON_BIN" - <<'PY'
import main

for name in (
    "read_unlock_token",
    "load_data_key",
    "save_wrapped_key",
):

    if not hasattr(main, name):
        raise SystemExit(
            "main.py missing " + name
        )

print("main.py import: PASS")
PY

###############################################################################
# FINAL LIBOQS DISCOVERY TEST
###############################################################################

section "33. FINAL LIBOQS LOCATION"

echo "OQS_INSTALL_PATH:"
echo "  $OQS_INSTALL_PATH"

echo
echo "Library:"
find "$OQS_INSTALL_PATH/lib" \
    -maxdepth 1 \
    -type f \
    -name 'liboqs.so*' \
    -print \
    2>/dev/null || true

###############################################################################
# FINAL KEYSTORE
###############################################################################

section "34. FINAL GATE 3 KEYSTORE STATE"

"$KEYSTORE" list

###############################################################################
# PRIVATE DATA FINAL CHECK
###############################################################################

section "35. FINAL DATA PRESERVATION"

for f in \
    "$NAZA_DIR/.enc_key" \
    "$NAZA_DIR/chat_history.db.aes" \
    "$NAZA_DIR/chat_history.db.aes.mac"
do

    if [ -e "$f" ]; then
        echo "PRESERVED: $f"
    fi

done

for d in \
    "$NAZA_DIR/models" \
    "$NAZA_DIR/.naza-private-tmp"
do

    if [ -d "$d" ]; then
        echo "PRESERVED: $d"
    fi

done

###############################################################################
# GIT STATUS
###############################################################################

section "36. GIT STATUS"

if [ -d "$NAZA_DIR/.git" ]; then
    git -C "$NAZA_DIR" status --short
else
    echo "Not a Git checkout."
fi

###############################################################################
# FINAL SUMMARY
###############################################################################

section "37. REPAIR COMPLETE"

cat <<SUMMARY

NAZA NATIVE TERMUX REPAIR COMPLETE
===================================

Naza:
  $NAZA_DIR

Backup:
  $BACKUP_DIR

Log:
  $LOG

Native execution:
  PASS

PRoot:
  NOT USED

termux-fingerprint:
  NOT USED

libpython LD_PRELOAD:
  NOT USED

liboqs:
  $OQS_INSTALL_PATH
  0.14.0
  VALIDATED

liboqs-python:
  0.12.0
  VALIDATED

ML-KEM-1024:
  PASS

HQC-256:
  PASS

X25519:
  PASS

HKDF-SHA512:
  PASS

AES-256-GCM:
  PASS

llama-cpp-python:
  0.3.1
  Android support repaired/validated

cryptography:
  46.0.5
  Android import/AES-GCM validated
  No libpython preload

Process hardening:
  non-dumpable: PASS
  no-new-privileges: PASS

Gate 3:
  Android Keystore
  RSA 2048
  secure hardware
  authentication required
  hardware enforced
  10-second validity

NKEY4:
  Existing key preserved
  No automatic rekey

Encrypted data:
  Preserved

Models:
  Preserved

Python syntax:
  PASS

Shell syntax:
  PASS

Security source scan:
  PASS

NEXT STEP
==========

Do NOT reinstall liboqs.

First generate a fresh Gate 3 token:

  bash ~/naza/naza_unlock.sh

If Android asks for authentication, authenticate the phone.

Then verify:

  cat ~/.naza/unlock.token

It should be exactly 64 lowercase hexadecimal characters.

Then start:

  bash ~/naza/naza-termux-boot.sh

Press:

  U

After Naza starts, test the existing tri-hybrid path.

Finally:

  cd ~/naza
  git status --short
  git diff --stat

Do NOT commit until the runtime test passes.

SUMMARY

echo
echo "================================================================"
echo " NATIVE TERMUX REPAIR FINISHED SUCCESSFULLY"
echo "================================================================"
echo
