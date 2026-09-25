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
REPAIR="$NAZA_DIR/repair-android-termux.sh"

[ -x "$UNLOCK" ] || { echo "ERROR: Gate 3 helper missing: $UNLOCK" >&2; exit 1; }
[ -x "$RUN" ] || { echo "ERROR: launcher missing: $RUN" >&2; exit 1; }
[ -f "$REPAIR" ] && [ ! -L "$REPAIR" ] || { echo "ERROR: secure repair installer missing or unsafe: $REPAIR" >&2; exit 1; }
[ "$(stat -c %u "$REPAIR")" = "$(id -u)" ] || { echo "ERROR: secure repair installer has wrong owner" >&2; exit 1; }
REPAIR_MODE="$(stat -c %a "$REPAIR")"
[ $((8#$REPAIR_MODE & 8#022)) -eq 0 ] || { echo "ERROR: secure repair installer is group/other writable" >&2; exit 1; }

while true; do
    clear 2>/dev/null || true
    cat <<'MENU'
╔══════════════════════════════════════════════════════════╗
║                                                          ║
║  ███╗   ██╗ █████╗ ███████╗ █████╗                     ║
║  ████╗  ██║██╔══██╗╚══███╔╝██╔══██╗                    ║
║  ██╔██╗ ██║███████║  ███╔╝ ███████║                    ║
║  ██║╚██╗██║██╔══██║ ███╔╝  ██╔══██║                    ║
║  ██║ ╚████║██║  ██║███████╗██║  ██║                    ║
║  ╚═╝  ╚═══╝╚═╝  ╚═╝╚══════╝╚═╝  ╚═╝                    ║
║                                                          ║
╠══════════════════════════════════════════════════════════╣
║                 Android Keystore Gate 3                  ║
║                                                          ║
║       Unlock/authenticate the phone, then choose:        ║
║                                                          ║
║       U = authorize + start Naza                         ║
║       R = secure repair/reinstall                        ║
║       Q = quit                                           ║
╚══════════════════════════════════════════════════════════╝
MENU
    printf '\nSelect [U/R/Q]: '
    IFS= read -r answer || exit 0
    case "$answer" in
        U|u)
            "$UNLOCK" || { echo "Gate 3 authorization failed." >&2; read -r -p "Press Enter..." _ || true; continue; }
            exec "$RUN"
            ;;
        R|r)
            echo "This validates and repairs the current OS-specific runtime."
            echo "Encrypted keys, history, models, and Gate 3 state are preserved."
            echo "It will never automatically rekey data after a device/kernel change."
            printf "Type REPAIR to continue: "
            IFS= read -r confirm || continue
            [ "$confirm" = "REPAIR" ] || { echo "Repair cancelled."; sleep 1; continue; }
            if bash "$REPAIR"; then
                echo "Secure repair completed and validated."
            else
                echo "Secure repair failed; encrypted state was not intentionally rekeyed." >&2
            fi
            read -r -p "Press Enter to return to the security menu..." _ || true
            ;;
        Q|q) exit 0 ;;
        *) echo "Invalid selection."; sleep 1 ;;
    esac
done
