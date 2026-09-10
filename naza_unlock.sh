#!/data/data/com.termux/files/usr/bin/bash
# Termux-only required biometric + Android keystore unlock token.
set -euo pipefail
HOME_T="${HOME:-/data/data/com.termux/files/home}"
NAZA_DIR="$HOME_T/.naza"
ALIAS="${NAZA_KEYSTORE_ALIAS:-naza-unlock}"
CHALLENGE="$NAZA_DIR/challenge"
TOKEN="$NAZA_DIR/unlock.token"
ALGO="${NAZA_SIGN_ALGO:-SHA256withRSA}"

mkdir -p "$NAZA_DIR"
chmod 700 "$NAZA_DIR" 2>/dev/null || true
command -v termux-fingerprint >/dev/null 2>&1 || { echo "ERROR: termux-fingerprint unavailable" >&2; exit 1; }
command -v termux-keystore >/dev/null 2>&1 || { echo "ERROR: termux-keystore unavailable" >&2; exit 1; }
termux-keystore list 2>/dev/null | grep -Fq "$ALIAS" || {
  echo "ERROR: required keystore alias '$ALIAS' is missing. Rerun setup.sh." >&2
  exit 1
}

if [ ! -f "$CHALLENGE" ]; then
  dd if=/dev/urandom bs=32 count=1 status=none | xxd -p -c 64 > "$CHALLENGE"
  chmod 600 "$CHALLENGE"
fi

AUTH="$(termux-fingerprint -t Naza -s Unlock -d 'Unlock Naza' | tr -d '\r')"
printf '%s\n' "$AUTH" | grep -q 'AUTH_RESULT_SUCCESS' || { echo "Fingerprint failed." >&2; exit 1; }
SIG="$(termux-keystore sign "$ALIAS" "$ALGO" < "$CHALLENGE" | tr -d '\r\n ')"
[ "${#SIG}" -ge 32 ] || { echo "Keystore signing failed." >&2; exit 1; }
printf '%s\n' "$(printf '%s' "$SIG" | sha256sum | awk '{print $1}')" > "$TOKEN"
chmod 600 "$TOKEN"
echo "Naza unlock token ready."
