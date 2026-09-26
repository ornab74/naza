#!/data/data/com.termux/files/usr/bin/bash
# NAZA Termux -> Ubuntu proot -> sudouser -> TUI installer/launcher
# Idempotent: safe to run again to repair the launcher/user/bootstrap path.
set -Eeuo pipefail
IFS=$'\n\t'

REPO_URL="https://github.com/ornab74/naza.git"
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

say "Cloning/updating NAZA as ${NAZA_USER}"
proot-distro login --user "$NAZA_USER" "$DISTRO_ALIAS" -- /bin/bash -lc '
set -Eeuo pipefail
REPO_URL="https://github.com/ornab74/naza.git"
APP="$HOME/naza"

if [ -d "$APP/.git" ]; then
    current="$(git -C "$APP" remote get-url origin 2>/dev/null || true)"
    if [ "$current" != "$REPO_URL" ]; then
        echo "ERROR: $APP exists but origin is $current" >&2
        exit 1
    fi
    git -C "$APP" fetch --prune origin
    git -C "$APP" checkout main
    git -C "$APP" reset --hard origin/main
else
    rm -rf "$APP"
    git clone "$REPO_URL" "$APP"
fi
'

say "Running the repository Ubuntu installer as ${NAZA_USER}"
# This is deliberately run as the real Ubuntu user. The repo installer itself uses sudo.
proot-distro login --user "$NAZA_USER" "$DISTRO_ALIAS" -- /bin/bash -lc '
set -Eeuo pipefail