#!/data/data/com.termux/files/usr/bin/bash
set -Eeuo pipefail
IFS=$'\n\t'
umask 077

PREFIX="${PREFIX:-/data/data/com.termux/files/usr}"
HOME="${HOME:-/data/data/com.termux/files/home}"
NAZA_DIR="${NAZA_DIR:-$HOME/naza}"
VENV="$NAZA_DIR/venv-termux"
OQS_PREFIX="$HOME/.local/liboqs-0.14.0"
KEYSTORE="$PREFIX/bin/termux-keystore"
TERMUX_EXEC="$PREFIX/lib/libtermux-exec.so"

say() { printf '\n==> %s\n' "$*"; }
die() { printf 'ERROR: %s\n' "$*" >&2; exit 1; }

[ -d "$NAZA_DIR" ] || die "Run this from an existing Naza checkout at $NAZA_DIR"
[ ! -L "$NAZA_DIR" ] || die "Refusing symbolic-link Naza directory"
chmod 700 "$NAZA_DIR"

say "Installing native Termux build prerequisites"
pkg update -y
pkg install -y \
  python clang cmake ninja make git curl rust binutils coreutils findutils grep sed tar gzip unzip termux-api

[ -x "$KEYSTORE" ] || die "termux-keystore is unavailable; install/repair the matching Termux:API environment"
[ -f "$TERMUX_EXEC" ] || die "libtermux-exec.so is missing"

say "Creating/reusing native Python environment"
if [ ! -x "$VENV/bin/python" ]; then
  python -m venv "$VENV"
fi
PY="$VENV/bin/python"
"$PY" -m pip install --upgrade pip setuptools wheel
"$PY" -m pip install \
  'httpx==0.28.1' \
  'aiosqlite==0.22.1' \
  'numpy==2.5.3' \
  'MarkupSafe==3.0.3' \
  'diskcache==5.6.3' \
  'Jinja2==3.1.6' \
  'typing-extensions==4.16.0'

say "Installing/reusing pinned Open Quantum Safe backend"
if ! OQS_INSTALL_PATH="$OQS_PREFIX" LD_LIBRARY_PATH="$OQS_PREFIX/lib" "$PY" - <<'PY' >/dev/null 2>&1
import oqs
need = {'ML-KEM-1024', 'HQC-256'}
assert oqs.__version__ == '0.12.0'
assert need.issubset(set(oqs.get_enabled_kem_mechanisms()))
PY
then
  PREFIX="$OQS_PREFIX" PYTHON_BIN="$PY" bash "$NAZA_DIR/install_liboqs_0.14.0.sh"
fi

say "Installing cryptography"
"$PY" -m pip install --force-reinstall 'cryptography==46.0.5' 'cffi==2.1.1' 'pycparser==3.0'

say "Installing llama-cpp-python"
"$PY" -m pip install 'llama-cpp-python==0.3.1'

# Some llama-cpp-python 0.3.1 builds classify Android separately from Linux.
LLAMA_EXT="$($PY - <<'PY'
import os, llama_cpp
print(os.path.join(os.path.dirname(llama_cpp.__file__), '_ctypes_extensions.py'))
PY
)"
if [ -f "$LLAMA_EXT" ] && ! grep -q 'sys.platform.startswith("android")' "$LLAMA_EXT"; then
  "$PY" - "$LLAMA_EXT" <<'PY'
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

say "Configuring Android Keystore Gate 3"
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

chmod 700 "$NAZA_DIR/naza_unlock.sh" "$NAZA_DIR/run_naza.sh"

say "Validating source and launchers"
"$PY" -m py_compile \
  "$NAZA_DIR/main.py" \
  "$NAZA_DIR/naza_storage.py" \
  "$NAZA_DIR/spooky_combiner.py" \
  "$NAZA_DIR/spooky_trihybrid.py" \
  "$NAZA_DIR/naza_crypto_preflight.py"
bash -n "$NAZA_DIR/naza_unlock.sh"
bash -n "$NAZA_DIR/run_naza.sh"

say "Crypto smoke checks"
OQS_INSTALL_PATH="$OQS_PREFIX" \
LD_LIBRARY_PATH="$OQS_PREFIX/lib" \
LD_PRELOAD="$TERMUX_EXEC" \
NAZA_CRYPTO_MODE=tri \
"$PY" - <<'PY'
import os, oqs
from cryptography.hazmat.primitives.asymmetric.x25519 import X25519PrivateKey
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
need = {'ML-KEM-1024', 'HQC-256'}
assert need.issubset(set(oqs.get_enabled_kem_mechanisms()))
a = X25519PrivateKey.generate(); b = X25519PrivateKey.generate()
assert a.exchange(b.public_key()) == b.exchange(a.public_key())
k = AESGCM.generate_key(bit_length=256); n = os.urandom(12); m = b'naza-native-termux'
c = AESGCM(k).encrypt(n, m, None)
assert AESGCM(k).decrypt(n, c, None) == m
print('ML-KEM-1024/HQC-256 availability: PASS')
print('X25519: PASS')
print('AES-256-GCM: PASS')
PY

cat <<'EOF'

Native Termux reconciliation complete.
Existing .enc_key, encrypted history, models, and application data were not rekeyed or intentionally deleted.

Next:
  bash ~/naza/naza_unlock.sh
  bash ~/naza/run_naza.sh
EOF
