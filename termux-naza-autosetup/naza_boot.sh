#!/data/data/com.termux/files/usr/bin/bash
# Required biometric/keystore unlock on Termux, then launch SpookyNaza in Ubuntu proot.
set -euo pipefail
HOME_T="${HOME:-/data/data/com.termux/files/home}"
UNLOCK_SH="$HOME_T/.naza/naza_unlock.sh"

[ -x "$UNLOCK_SH" ] || { echo "ERROR: missing $UNLOCK_SH" >&2; exit 1; }
bash "$UNLOCK_SH" || { echo "Unlock failed. Naza was not started." >&2; exit 1; }

proot-distro login ubuntu --user sudouser --shared-tmp \
  --bind "$HOME_T/.naza:/home/sudouser/.naza" -- bash -lc '
    set -e
    cd /home/sudouser/naza
    export NAZA_UNLOCK_FILE=/home/sudouser/.naza/unlock.token
    export NAZA_CRYPTO_MODE=tri
    export OQS_INSTALL_PATH=/home/sudouser/.local/liboqs-0.14.0
    export LD_LIBRARY_PATH="$OQS_INSTALL_PATH/lib${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"
    export TERM="${TERM:-xterm-256color}" LANG=C.UTF-8 PYTHONUNBUFFERED=1
    exec ./run_naza.sh
  '
