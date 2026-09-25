#!/data/data/com.termux/files/usr/bin/bash
# Required biometric/keystore unlock on Termux, then launch SpookyNaza in Ubuntu proot.
set -euo pipefail
umask 077
HOME_T="${HOME:-/data/data/com.termux/files/home}"
UNLOCK_SH="$HOME_T/.naza/naza_unlock.sh"
SETUP_SH="$HOME_T/naza/termux-naza-autosetup/setup.sh"

proot-distro login --help 2>&1 | grep -q -- '--isolated' || {
  echo "ERROR: proot-distro lacks required --isolated mode" >&2; exit 1;
}

[ -x "$UNLOCK_SH" ] && [ ! -L "$UNLOCK_SH" ] || { echo "ERROR: unsafe or missing $UNLOCK_SH" >&2; exit 1; }
[ "$(stat -c %u "$UNLOCK_SH")" = "$(id -u)" ] || { echo "ERROR: unlock helper has wrong owner" >&2; exit 1; }
while true; do
  clear 2>/dev/null || true
  cat <<'MENU'
NAZA SECURITY — Ubuntu/proot

U = authorize + start Naza
R = secure repair/reinstall Ubuntu runtime
Q = quit
MENU
  printf "\nSelect [U/R/Q]: "
  IFS= read -r answer || exit 0
  case "$answer" in
    U|u)

chmod 700 "$UNLOCK_SH"
# Preserve interactive stdin and stream directly from the authenticated helper.
# Python treats descriptor 9 as mandatory, so helper failure/EOF cannot fall back.
exec 9< <(NAZA_TOKEN_OUTPUT=stdout bash "$UNLOCK_SH")

proot-distro login ubuntu --isolated --user sudouser \
  -- bash -lc '
    set -eu
    umask 077
    ulimit -c 0
    ulimit -n 256
    cd /home/sudouser/naza
    export NAZA_UNLOCK_FD=9
    export NAZA_CRYPTO_MODE=tri
    export OQS_INSTALL_PATH=/home/sudouser/.local/liboqs-0.14.0
    unset LD_PRELOAD PYTHONPATH PYTHONHOME PYTHONINSPECT PYTHONSTARTUP
    export LD_LIBRARY_PATH="$OQS_INSTALL_PATH/lib"
    export TERM="${TERM:-xterm-256color}" LANG=C.UTF-8 PYTHONUNBUFFERED=1
    exec ./run_naza.sh
  '
      exec 9<&-
      ;;
    R|r)
      [ -f "$SETUP_SH" ] && [ ! -L "$SETUP_SH" ] || { echo "ERROR: secure Ubuntu installer missing or unsafe: $SETUP_SH" >&2; sleep 2; continue; }
      [ "$(stat -c %u "$SETUP_SH")" = "$(id -u)" ] || { echo "ERROR: Ubuntu installer has wrong owner" >&2; sleep 2; continue; }
      setup_mode="$(stat -c %a "$SETUP_SH")"
      [ $((8#$setup_mode & 8#022)) -eq 0 ] || { echo "ERROR: Ubuntu installer is group/other writable" >&2; sleep 2; continue; }
      echo "This repairs Ubuntu/proot packages and preserves encrypted NAZA state."
      echo "It never automatically rekeys data after an OS, kernel, or device change."
      printf "Type REPAIR to continue: "
      IFS= read -r confirm || continue
      [ "$confirm" = "REPAIR" ] || { echo "Repair cancelled."; sleep 1; continue; }
      bash "$SETUP_SH" || echo "Secure Ubuntu repair failed; encrypted state was not intentionally rekeyed." >&2
      read -r -p "Press Enter to return to the security menu..." _ || true
      ;;
    Q|q) exit 0 ;;
    *) echo "Invalid selection."; sleep 1 ;;
  esac
done
