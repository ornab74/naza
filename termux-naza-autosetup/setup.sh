#!/data/data/com.termux/files/usr/bin/bash
# NAZA Termux -> Ubuntu proot -> sudouser -> TUI installer/launcher
# Idempotent: safe to run again to repair the launcher/user/bootstrap path.
set -Eeuo pipefail
IFS=$'\n\t'

REPO_URL="https://github.com/ornab74/naza.git"
NAZA_REF="aa3f3056c883223734af0aff311757dc91f5233e"
DISTRO_ALIAS="ubuntu"
DISTRO_IMAGE="ubuntu:24.04"
NAZA_USER="sudouser"
NAZA_HOME="/home/${NAZA_USER}"
NAZA_DIR="${NAZA_HOME}/naza"
TERMUX_LAUNCHER="${HOME}/.local/bin/naza"
BASHRC="${HOME}/.bashrc"
AUTOSTART_BEGIN="# >>> NAZA PROOT AUTOSTART >>>"
AUTOSTART_END="# <<< NAZA PROOT AUTOSTART <<<"

say() { printf '\n\033[1;36m==> %s\033[0m\n' "$*"; }
warn() { printf '\033[1;33mWARN: %s\033[0m\n' "$*" >&2; }
die() { printf '\033[1;31mERROR: %s\033[0m\n' "$*" >&2; exit 1; }

trap 'printf "\nERROR at line %s: %s\n" "$LINENO" "$BASH_COMMAND" >&2' ERR

# Must run in real Termux, not inside the proot container.
[ -n "${PREFIX:-}" ] || die "PREFIX is not set. Run this from Termux."
case "$PREFIX" in
  /data/data/com.termux/files/usr) ;;
  *) warn "PREFIX is '$PREFIX'. This does not look like the standard Termux prefix." ;;
esac

say "Updating Termux and installing current proot-distro"
pkg update -y
pkg install -y proot-distro git curl ca-certificates bash coreutils ncurses-utils

command -v proot-distro >/dev/null 2>&1 || die "proot-distro was not installed correctly."

# Do NOT pin an old proot-distro checkout. Current Termux packages are the supported path.
say "Checking Ubuntu proot"
if ! proot-distro list 2>/dev/null | grep -Eq 'ubuntu.*installed|installed.*ubuntu'; then
    # Current proot-distro supports OCI-like image selectors. Fall back for older packaged builds.
    if ! proot-distro install "$DISTRO_IMAGE"; then
        warn "Version-pinned install failed; falling back to 'ubuntu'."
        proot-distro install "$DISTRO_ALIAS"
    fi
else
    say "Ubuntu already appears installed; keeping it."
fi

say "Creating/repairing Ubuntu user: ${NAZA_USER}"
proot-distro login "$DISTRO_ALIAS" -- /bin/bash -s <<ROOT_EOF
set -Eeuo pipefail
export DEBIAN_FRONTEND=noninteractive

apt-get update
apt-get install -y sudo git curl ca-certificates bash python3 python3-pip python3-venv python3-dev \
    build-essential cmake ninja-build pkg-config libssl-dev

if ! id -u "${NAZA_USER}" >/dev/null 2>&1; then
    useradd -m -s /bin/bash "${NAZA_USER}"
fi

# Ensure the home really exists and belongs to the requested user.
mkdir -p "${NAZA_HOME}"
chown -R "${NAZA_USER}:${NAZA_USER}" "${NAZA_HOME}"

# Passwordless sudo, installed as a separate validated sudoers fragment.
printf '%s\n' '${NAZA_USER} ALL=(ALL:ALL) NOPASSWD:ALL' > /etc/sudoers.d/90-naza-${NAZA_USER}
chmod 0440 /etc/sudoers.d/90-naza-${NAZA_USER}
visudo -cf /etc/sudoers.d/90-naza-${NAZA_USER} >/dev/null
ROOT_EOF

say "Cloning/updating NAZA as ${NAZA_USER} at pinned commit ${NAZA_REF}"
proot-distro login --user "$NAZA_USER" "$DISTRO_ALIAS" -- /bin/bash -lc '
set -Eeuo pipefail
REPO_URL="https://github.com/ornab74/naza.git"
NAZA_REF="aa3f3056c883223734af0aff311757dc91f5233e"
APP="$HOME/naza"

if [ -d "$APP/.git" ]; then
    current="$(git -C "$APP" remote get-url origin 2>/dev/null || true)"
    if [ "$current" != "$REPO_URL" ]; then
        echo "ERROR: $APP exists but origin is $current" >&2
        exit 1
    fi
else
    rm -rf "$APP"
    git clone "$REPO_URL" "$APP"
fi

git -C "$APP" fetch --prune origin
git -C "$APP" fetch origin "$NAZA_REF"
git -C "$APP" checkout --detach "$NAZA_REF"

actual="$(git -C "$APP" rev-parse HEAD)"
if [ "$actual" != "$NAZA_REF" ]; then
    echo "ERROR: pinned checkout verification failed." >&2
    echo "Expected: $NAZA_REF" >&2
    echo "Actual:   $actual" >&2
    exit 1
fi

echo "Pinned NAZA checkout verified: $actual"
'

say "Running the repository Ubuntu installer as ${NAZA_USER}"
# This is deliberately run as the real Ubuntu user. The repo installer itself uses sudo.
proot-distro login --user "$NAZA_USER" "$DISTRO_ALIAS" -- /bin/bash -lc '
set -Eeuo pipefail
cd "$HOME/naza"
chmod +x termux-naza-autosetup/setup_ubuntu.sh
NAZA_APP_DIR="$HOME/naza" NAZA_REPO_URL="https://github.com/ornab74/naza.git" NAZA_REF="aa3f3056c883223734af0aff311757dc91f5233e" \
    bash termux-naza-autosetup/setup_ubuntu.sh
'

say "Installing a stable Termux launcher"
mkdir -p "$(dirname "$TERMUX_LAUNCHER")"

cat > "$TERMUX_LAUNCHER" <<'LAUNCHER'
#!/data/data/com.termux/files/usr/bin/bash
set -Eeuo pipefail

DISTRO="ubuntu"
USER_NAME="sudouser"

export TERM="${TERM:-xterm-256color}"

printf '\n'
printf '╔══════════════════════════════════════════════════════════╗\n'
printf '║                 Starting NAZA TUI                       ║\n'
printf '║        Termux → Ubuntu proot → sudouser → NAZA         ║\n'
printf '╚══════════════════════════════════════════════════════════╝\n'
printf '\n'

# Keep stdin/stdout/stderr attached to the current interactive Termux terminal.
exec proot-distro login --user "$USER_NAME" "$DISTRO" -- /bin/bash -lc '
set -Eeuo pipefail
cd "$HOME/naza"

export TERM="${TERM:-xterm-256color}"
export LANG="${LANG:-C.UTF-8}"
export LC_ALL="${LC_ALL:-C.UTF-8}"
export PYTHONUNBUFFERED=1
export OQS_INSTALL_PATH="$HOME/.local/liboqs-0.14.0"
export LD_LIBRARY_PATH="$OQS_INSTALL_PATH/lib${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"
export NAZA_CRYPTO_MODE=tri

# Ubuntu uses venv/, not the native-Termux venv-termux/.
if [ ! -x "$HOME/naza/venv/bin/python" ]; then
    echo "ERROR: Ubuntu NAZA venv is missing: $HOME/naza/venv" >&2
    echo "Re-run the installer/repair script." >&2
    exit 1
fi

# The repository run_naza.sh is the native Termux launcher and contains
# Termux-specific paths. Inside Ubuntu, execute the Ubuntu venv directly.
if [ -f "$HOME/naza/naza_crypto_preflight.py" ]; then
    "$HOME/naza/venv/bin/python" "$HOME/naza/naza_crypto_preflight.py"
fi

exec "$HOME/naza/venv/bin/python" -u "$HOME/naza/main.py"
'
LAUNCHER
chmod 0755 "$TERMUX_LAUNCHER"

# Make ~/.local/bin available for this and future shells.
if ! grep -Fq 'export PATH="$HOME/.local/bin:$PATH"' "$BASHRC" 2>/dev/null; then
    printf '\nexport PATH="$HOME/.local/bin:$PATH"\n' >> "$BASHRC"
fi

say "Installing idempotent interactive-shell autostart"
# Remove any previous block produced by this repaired installer.
if [ -f "$BASHRC" ]; then
    tmp="${BASHRC}.naza.$$"
    awk -v begin="$AUTOSTART_BEGIN" -v end="$AUTOSTART_END" '
        $0 == begin {skip=1; next}
        $0 == end   {skip=0; next}
        !skip       {print}
    ' "$BASHRC" > "$tmp"
    mv "$tmp" "$BASHRC"
fi

cat >> "$BASHRC" <<'BASHRC_BLOCK'

# >>> NAZA PROOT AUTOSTART >>>
# Start only in a real interactive Termux shell.
# NAZA_NO_AUTOSTART=1 bash   -> opens Termux without launching NAZA.
case $- in
  *i*)
    if [ -z "${NAZA_NO_AUTOSTART:-}" ] &&
       [ -z "${NAZA_AUTOSTART_ACTIVE:-}" ] &&
       [ -z "${SSH_CLIENT:-}" ] &&
       [ -z "${SSH_TTY:-}" ]; then
        export NAZA_AUTOSTART_ACTIVE=1
        if [ -x "$HOME/.local/bin/naza" ]; then
            "$HOME/.local/bin/naza"
            rc=$?
            unset NAZA_AUTOSTART_ACTIVE
            printf '\nReturned to Termux (NAZA exit code: %s).\n' "$rc"
        fi
    fi
    ;;
esac
# <<< NAZA PROOT AUTOSTART <<<
BASHRC_BLOCK

say "Validating launcher"
bash -n "$TERMUX_LAUNCHER"
bash -n "$BASHRC"

cat <<EOF

Installation/repair complete.

Manual start:
  naza

Open Ubuntu as the proper user:
  proot-distro login --user ${NAZA_USER} ${DISTRO_ALIAS}

Open Termux WITHOUT autostarting NAZA:
  NAZA_NO_AUTOSTART=1 bash

Pinned NAZA commit:
  aa3f3056c883223734af0aff311757dc91f5233e

Expected path:
  Termux
    -> proot-distro Ubuntu
      -> ${NAZA_USER} (${NAZA_HOME})
        -> ${NAZA_DIR}/venv
          -> naza_crypto_preflight.py
          -> main.py

Close and reopen Termux, or run:
  exec bash

EOF
