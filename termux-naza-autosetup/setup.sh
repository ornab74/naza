#!/data/data/com.termux/files/usr/bin/bash
# ============================================================
# Termux → Ubuntu proot → Naza FULL AUTO-SETUP + AUTO-START
# Works 100% in December 2025 – full interactive TUI guaranteed
# ============================================================

set -euo pipefail

PROOT_DISTRO_DIR="${HOME}/proot-distro"
PROOT_DISTRO_REF="ca53fee288be8f46ee0e4fc8ee23934023472054"
NAZA_REF="${NAZA_REF:-main}"

echo "Updating Termux packages..."
pkg update -y && pkg upgrade -y
pkg install -y bash bzip2 coreutils curl file findutils gawk gzip ncurses-utils proot sed tar util-linux xz-utils git wget

echo "Cloning OLD working proot-distro commit (ca53fee – full TTY support)..."
if [ -e "$PROOT_DISTRO_DIR" ]; then
    echo "Refusing to replace existing path: $PROOT_DISTRO_DIR" >&2
    echo "Move it aside manually if you want a fresh installation." >&2
    exit 1
fi
git clone https://github.com/termux/proot-distro.git "$PROOT_DISTRO_DIR"
git -C "$PROOT_DISTRO_DIR" checkout --detach "$PROOT_DISTRO_REF"
cd "$PROOT_DISTRO_DIR"

echo "Installing proot-distro from this commit..."
chmod +x install.sh
./install.sh

echo "Installing Ubuntu (24.04 rootfs)..."
proot-distro install ubuntu

echo "Creating TMP dir..."
export PROOT_TMP_DIR=$HOME/tmp
mkdir -p $PROOT_TMP_DIR

echo "Setting up sudouser + Python + Naza repo..."
proot-distro login ubuntu -- env NAZA_REF="$NAZA_REF" bash <<'EOF'
apt update && apt upgrade -y
apt install -y sudo python3 python3-pip python3-venv git nano curl

# Create an unprivileged runtime user. Setup continues as root in this block;
# the application itself does not need sudo access.
adduser --disabled-password --gecos "" sudouser

# Clone naza repo
su - sudouser -c "
    mkdir -p ~/naza && cd ~/naza
    git clone https://github.com/ornab74/naza.git .
    git checkout --detach '$NAZA_REF'
    python3 -m venv venv
    source venv/bin/activate
    pip install --upgrade pip
    [ -f requirements.txt ] && pip install --require-hashes -r requirements.txt
    chmod +x main.py
"

echo "Setup complete inside Ubuntu"
EOF

# ============================================================
# FINAL STEP: FORCE AUTO-START WITH YOUR EXACT BANNER + FULL TTY
# ============================================================

if ! grep -q '^# === BEGIN NAZA AUTO-START ===$' "$HOME/.bashrc" 2>/dev/null; then
cat >> "$HOME/.bashrc" <<'BASHRC'
# === BEGIN NAZA AUTO-START ===
# === AUTO-START SECURELLM IN UBUNTU PROOT (naza folder + venv) ===
if [ -z "$NAZA_STARTED" ] && [ "$PWD" = "$HOME" ] && [ -z "$SSH_CLIENT" ] && [ -z "$TMUX" ]; then
    export NAZA_STARTED=1

    echo ""
    echo "╔══════════════════════════════════════════════════════════╗"
    echo "║          Starting SecureLLM TUI (naza/main.py)           ║"
    echo "║        Ubuntu proot → /home/sudouser/naza                ║"
    echo "╚══════════════════════════════════════════════════════════╝"
    echo "   Type 'exit' twice to return to Termux"
    echo ""

    proot-distro login ubuntu --user sudouser --shared-tmp -- bash -c "
        cd /home/sudouser/naza || exit 1
        
        # Activate venv
        source venv/bin/activate || exit 1
        
        # Fix terminal + locale + unbuffered output
        export TERM=xterm-256color
        export LANG=C.UTF-8
        export PYTHONUNBUFFERED=1
        
        # Run your TUI interactively with full pseudo-tty
        clear
        echo 'Starting main.py in venv...'
        exec python -u main.py
    "
    
    clear
    echo "Returned to Termux."
fi

# Optional manual start alias.
alias naza='proot-distro login ubuntu --user sudouser -- bash -c "cd ~/naza && source venv/bin/activate && python -u main.py"'
# === END NAZA AUTO-START ===
BASHRC
fi

echo "--------------------------------------------------------------"
echo "ALL DONE!"
echo "Close and reopen Termux (or run: bash)"
echo "Your SecureLLM TUI will now auto-start with full colors & interactivity"
echo "Enjoy your encrypted quantum-entropic road-scanner on the go!"
echo "--------------------------------------------------------------"
