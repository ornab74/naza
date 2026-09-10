#!/data/data/com.termux/files/usr/bin/bash
# Required Termux keystore -> Ubuntu proot -> SpookyNaza + pinned liboqs.
set -euo pipefail

NAZA_REF="${NAZA_REF:-main}"
REPO_URL="${NAZA_REPO_URL:-https://github.com/ornab74/naza.git}"
KEY_ALIAS="${NAZA_KEYSTORE_ALIAS:-naza-unlock}"
HERE="$(cd "$(dirname "$0")" && pwd)"

fail() { echo "ERROR: $*" >&2; exit 1; }

printf '\n==> Updating Termux and installing required host packages\n'
pkg update -y
pkg upgrade -y
pkg install -y git curl coreutils proot-distro termux-api xxd

command -v termux-keystore >/dev/null 2>&1 || \
  fail "termux-keystore is unavailable. Install the Termux:API Android companion app, then rerun this installer."
command -v termux-fingerprint >/dev/null 2>&1 || \
  fail "termux-fingerprint is unavailable. Install the Termux:API Android companion app, then rerun this installer."

printf '\n==> Enforcing required Android/Termux keystore key: %s\n' "$KEY_ALIAS"
KEY_LIST="$(termux-keystore list 2>/dev/null || true)"
if ! printf '%s\n' "$KEY_LIST" | grep -Fq "$KEY_ALIAS"; then
  termux-keystore generate "$KEY_ALIAS" -a RSA -s 2048 -u 10 || \
    fail "could not generate required Termux keystore alias '$KEY_ALIAS'"
fi
KEY_LIST="$(termux-keystore list 2>/dev/null || true)"
printf '%s\n' "$KEY_LIST" | grep -Fq "$KEY_ALIAS" || \
  fail "required Termux keystore alias '$KEY_ALIAS' was not found after generation"
echo "Required keystore alias verified: $KEY_ALIAS"

mkdir -p "$HOME/.naza"
chmod 700 "$HOME/.naza"
for helper in naza_unlock.sh naza_boot.sh; do
  [ -f "$HERE/$helper" ] || fail "missing installer helper: $HERE/$helper"
  cp "$HERE/$helper" "$HOME/.naza/$helper"
  chmod 700 "$HOME/.naza/$helper"
done

printf '\n==> Installing Ubuntu proot if needed\n'
if proot-distro login ubuntu -- true >/dev/null 2>&1; then
  echo "Ubuntu proot already present; reusing it."
else
  proot-distro install ubuntu
fi

export PROOT_TMP_DIR="$HOME/tmp"
mkdir -p "$PROOT_TMP_DIR"

printf '\n==> Installing SpookyNaza + pinned liboqs inside Ubuntu\n'
proot-distro login ubuntu -- env NAZA_REF="$NAZA_REF" NAZA_REPO_URL="$REPO_URL" bash <<'PROOT_EOF'
set -euo pipefail
export DEBIAN_FRONTEND=noninteractive
apt update
apt upgrade -y
apt install -y \
  sudo git curl ca-certificates build-essential cmake ninja-build pkg-config libssl-dev \
  python3 python3-pip python3-venv python3-dev

id -u sudouser >/dev/null 2>&1 || adduser --disabled-password --gecos "" sudouser

cat > /tmp/naza-proot-install.sh <<'INNER_EOF'
set -euo pipefail
APP_DIR="$HOME/naza"
REPO_URL="${NAZA_REPO_URL:-https://github.com/ornab74/naza.git}"
NAZA_REF="${NAZA_REF:-main}"

if [ -d "$APP_DIR/.git" ]; then
  git -C "$APP_DIR" fetch --prune origin "$NAZA_REF"
else
  rm -rf "$APP_DIR"
  git clone "$REPO_URL" "$APP_DIR"
  git -C "$APP_DIR" fetch --prune origin "$NAZA_REF"
fi
# Resolve the requested ref now and detach so the installed tree cannot drift silently.
git -C "$APP_DIR" checkout --detach FETCH_HEAD

python3 -m venv "$APP_DIR/venv"
. "$APP_DIR/venv/bin/activate"
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
export PYTHON_BIN="$APP_DIR/venv/bin/python"
"$APP_DIR/install_liboqs_0.14.0.sh"

export OQS_INSTALL_PATH="$HOME/.local/liboqs-0.14.0"
export LD_LIBRARY_PATH="$OQS_INSTALL_PATH/lib${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"
export NAZA_CRYPTO_MODE=tri
"$APP_DIR/venv/bin/python" - <<'PY'
import oqs
import spooky_trihybrid
mechs = set(oqs.get_enabled_kem_mechanisms())
missing = {"ML-KEM-1024", "HQC-256"} - mechs
if missing:
    raise SystemExit("SpookyNaza install failed; missing OQS mechanisms: " + ", ".join(sorted(missing)))
print("SpookyNaza default verified: tri-hybrid NKEY4 + ML-KEM-1024 + HQC-256 + X25519")
PY
INNER_EOF
chmod 700 /tmp/naza-proot-install.sh
chown sudouser:sudouser /tmp/naza-proot-install.sh
su - sudouser -c "NAZA_REF='$NAZA_REF' NAZA_REPO_URL='$NAZA_REPO_URL' bash /tmp/naza-proot-install.sh"
rm -f /tmp/naza-proot-install.sh
PROOT_EOF

if ! grep -q '^# === BEGIN NAZA AUTO-START ===$' "$HOME/.bashrc" 2>/dev/null; then
cat >> "$HOME/.bashrc" <<'BASHRC'
# === BEGIN NAZA AUTO-START ===
if [ -z "${NAZA_STARTED:-}" ] && [ "$PWD" = "$HOME" ] && [ -z "${SSH_CLIENT:-}" ] && [ -z "${TMUX:-}" ]; then
    export NAZA_STARTED=1
    if [ -x "$HOME/.naza/naza_boot.sh" ]; then
        bash "$HOME/.naza/naza_boot.sh"
    fi
fi
alias naza='bash "$HOME/.naza/naza_boot.sh"'
alias naza-unlock='bash "$HOME/.naza/naza_unlock.sh"'
# === END NAZA AUTO-START ===
BASHRC
fi

echo
echo "=============================================================="
echo "Naza installation complete."
echo "Required Termux keystore alias: $KEY_ALIAS"
echo "Default crypto mode: SpookyNaza tri-hybrid (NKEY4)"
echo "Pinned liboqs: 0.14.0, verified before build"
echo "Reopen Termux or run: naza"
echo "=============================================================="
