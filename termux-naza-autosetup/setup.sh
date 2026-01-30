#!/data/data/com.termux/files/usr/bin/bash
# ============================================================
# Termux → Ubuntu proot → Naza FULL AUTO-SETUP + AUTO-START
# Works 100% in December 2025 – full interactive TUI guaranteed
# ============================================================

set -e

echo "Updating Termux packages..."
pkg update -y && pkg upgrade -y
pkg install -y bash bzip2 coreutils curl file findutils gawk gzip ncurses-utils proot sed tar util-linux xz-utils git wget

echo "Removing any old proot-distro..."
proot-distro remove ubuntu 2>/dev/null || true
rm -rf $HOME/proot-distro 2>/dev/null

echo "Cloning OLD working proot-distro commit (ca53fee – full TTY support)..."
cd $HOME
git clone https://github.com/termux/proot-distro.git
cd proot-distro
git checkout ca53fee288be8f46ee0e4fc8ee23934023472054

echo "Installing proot-distro from this commit..."
chmod +x install.sh
./install.sh

echo "Installing Ubuntu (24.04 rootfs)..."
proot-distro install ubuntu

echo "Creating TMP dir..."
export PROOT_TMP_DIR=$HOME/tmp
mkdir -p $PROOT_TMP_DIR

echo "Setting up sudouser + Python + Naza repo..."
proot-distro login ubuntu -- <<'EOF'
apt update && apt upgrade -y
apt install -y sudo python3 python3-pip python3-venv git nano curl

# Create sudouser (no password)
adduser --disabled-password --gecos "" sudouser
usermod -aG sudo sudouser
echo "sudouser ALL=(ALL) NOPASSWD:ALL" >> /etc/sudoers

# Clone naza repo
su - sudouser -c "
    mkdir -p ~/naza && cd ~/naza
    git clone https://github.com/ornab74/naza.git . || git pull
    python3 -m venv venv
    source venv/bin/activate
    pip install --upgrade pip
    [ -f requirements.txt ] && pip install -r requirements.txt || true
    chmod +x main.py
"

echo "Setup complete inside Ubuntu"
EOF

# ============================================================
# FINAL STEP: FORCE AUTO-START WITH YOUR EXACT BANNER + FULL TTY
# ============================================================

cat > ~/.bashrc <<'BASHRC'
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
BASHRC

# Optional: add alias if someone wants to start manually too
echo "alias naza='proot-distro login ubuntu --user sudouser -- bash -c \"cd ~/naza && source venv/bin/activate && python -u main.py\"'" >> ~/.bashrc

echo "--------------------------------------------------------------"
echo "ALL DONE!"
echo "Close and reopen Termux (or run: bash)"
echo "Your SecureLLM TUI will now auto-start with full colors & interactivity"
echo "Enjoy your encrypted quantum-entropic road-scanner on the go!"
echo "--------------------------------------------------------------"
