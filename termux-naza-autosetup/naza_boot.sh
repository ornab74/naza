#!/data/data/com.termux/files/usr/bin/bash
# Required biometric/keystore unlock on Termux, then launch SpookyNaza in Ubuntu proot.
set -euo pipefail
umask 077
HOME_T="${HOME:-/data/data/com.termux/files/home}"
UNLOCK_SH="$HOME_T/.naza/naza_unlock.sh"
HOST_TOKEN="$HOME_T/.naza/unlock.token"

[ -x "$UNLOCK_SH" ] && [ ! -L "$UNLOCK_SH" ] || { echo "ERROR: unsafe or missing $UNLOCK_SH" >&2; exit 1; }
[ "$(stat -c %u "$UNLOCK_SH")" = "$(id -u)" ] || { echo "ERROR: unlock helper has wrong owner" >&2; exit 1; }
chmod 700 "$UNLOCK_SH"
bash "$UNLOCK_SH" || { echo "Unlock failed. Naza was not started." >&2; exit 1; }
[ -f "$HOST_TOKEN" ] && [ ! -L "$HOST_TOKEN" ] || { echo "ERROR: unsafe unlock token" >&2; exit 1; }
[ "$(stat -c %u "$HOST_TOKEN")" = "$(id -u)" ] || { echo "ERROR: unlock token has wrong owner" >&2; exit 1; }
[ "$(stat -c %a "$HOST_TOKEN")" = "600" ] || { echo "ERROR: unlock token has unsafe permissions" >&2; exit 1; }
[ "$(wc -c < "$HOST_TOKEN")" -eq 65 ] && grep -Eq '^[0-9a-f]{64}$' "$HOST_TOKEN" || {
  echo "ERROR: malformed unlock token" >&2; exit 1;
}

# Copy only the one-time token into the guest. Never bind the host control
# directory writable into proot, where a compromised guest could replace the
# next-boot launcher or unlock helper.
proot-distro login ubuntu --user sudouser -- bash -c '
  set -eu
  umask 077
  mkdir -p "$HOME/.naza"
  tmp="$(mktemp "$HOME/.naza/.unlock.token.XXXXXX")"
  trap '\''rm -f -- "$tmp"'\'' EXIT
  cat > "$tmp"
  chmod 600 "$tmp"
  mv -f -- "$tmp" "$HOME/.naza/unlock.token"
' < "$HOST_TOKEN"
rm -f -- "$HOST_TOKEN"

proot-distro login ubuntu --user sudouser \
  -- bash -lc '
    set -e
    cd /home/sudouser/naza
    export NAZA_UNLOCK_FILE=/home/sudouser/.naza/unlock.token
    export NAZA_CRYPTO_MODE=tri
    export OQS_INSTALL_PATH=/home/sudouser/.local/liboqs-0.14.0
    unset LD_PRELOAD PYTHONPATH PYTHONHOME PYTHONINSPECT PYTHONSTARTUP
    export LD_LIBRARY_PATH="$OQS_INSTALL_PATH/lib"
    export TERM="${TERM:-xterm-256color}" LANG=C.UTF-8 PYTHONUNBUFFERED=1
    exec ./run_naza.sh
  '
