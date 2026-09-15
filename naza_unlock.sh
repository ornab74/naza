#!/data/data/com.termux/files/usr/bin/bash
set -Eeuo pipefail
IFS=$'\n\t'
umask 077

PREFIX="${PREFIX:-/data/data/com.termux/files/usr}"
HOME_T="${HOME:-/data/data/com.termux/files/home}"
CONTROL="$HOME_T/.naza"
KEYSTORE="$PREFIX/bin/termux-keystore"
ALIAS="naza-unlock"
CHALLENGE="$CONTROL/challenge"
SIGNATURE="$CONTROL/signature"
TOKEN="$CONTROL/unlock.token"

export LD_PRELOAD="$PREFIX/lib/libtermux-exec.so"

die() { rm -f -- "$CHALLENGE" "$SIGNATURE" 2>/dev/null || true; echo "ERROR: $*" >&2; exit 1; }
mkdir -p "$CONTROL"
[ ! -L "$CONTROL" ] || die ".naza control directory is a symlink"
chmod 700 "$CONTROL"
[ -x "$KEYSTORE" ] || die "termux-keystore unavailable"

STATE="$($PREFIX/bin/python - "$KEYSTORE" <<'PY'
import json, subprocess, sys
items = json.loads(subprocess.check_output([sys.argv[1], 'list'], text=True))
for item in items:
    if item.get('alias') != 'naza-unlock':
        continue
    auth = item.get('user_authentication') or {}
    good = (
        item.get('algorithm') == 'RSA'
        and int(item.get('size', 0)) == 2048
        and bool(item.get('inside_secure_hardware'))
        and bool(auth.get('required'))
        and bool(auth.get('enforced_by_secure_hardware'))
        and int(auth.get('validity_duration_seconds', -1)) == 10
    )
    print('CORRECT' if good else 'WRONG')
    raise SystemExit
print('MISSING')
PY
)"
[ "$STATE" = CORRECT ] || die "naza-unlock does not satisfy Gate 3 hardware policy"

rm -f -- "$CHALLENGE" "$SIGNATURE"
$PREFIX/bin/python - <<'PY' > "$CHALLENGE"
import secrets
print(secrets.token_hex(32), end='')
PY
chmod 600 "$CHALLENGE"
grep -Eq '^[0-9a-f]{64}$' "$CHALLENGE" || die "challenge generation failed"

echo "Android Keystore hardware authentication is required."
"$KEYSTORE" sign "$ALIAS" SHA256withRSA "$CHALLENGE" "$SIGNATURE" || die "Android Keystore signing failed"
[ -s "$SIGNATURE" ] || die "Android Keystore returned no signature"

TOKEN_VALUE="$($PREFIX/bin/python - "$CHALLENGE" "$SIGNATURE" <<'PY'
from pathlib import Path
import hashlib, sys
challenge = Path(sys.argv[1]).read_text().strip().encode('ascii')
signature = Path(sys.argv[2]).read_bytes()
print(hashlib.sha256(challenge + signature).hexdigest())
PY
)"
printf '%s\n' "$TOKEN_VALUE" | grep -Eq '^[0-9a-f]{64}$' || die "invalid token format"
TMP="$(mktemp "$CONTROL/.unlock.token.XXXXXX")"
chmod 600 "$TMP"
printf '%s\n' "$TOKEN_VALUE" > "$TMP"
mv -f -- "$TMP" "$TOKEN"
chmod 600 "$TOKEN"
rm -f -- "$CHALLENGE" "$SIGNATURE"
unset TOKEN_VALUE
printf 'Gate 3 hardware-backed token ready: %s\n' "$TOKEN"
