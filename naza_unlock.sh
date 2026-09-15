#!/data/data/com.termux/files/usr/bin/bash

###############################################################################
# NAZA GATE 3
#
# Native Termux Android Keystore authentication.
#
# No biometric-specific Termux API.
#
# Existing Naza token protocol:
#
#   random challenge
#   Android Keystore SHA256withRSA signature
#   SHA256(challenge + signature)
#   64 lowercase hexadecimal characters
#
###############################################################################

set -Eeuo pipefail
IFS=$'\n\t'
umask 077

PREFIX="${PREFIX:-/data/data/com.termux/files/usr}"
HOME_T="${HOME:-/data/data/com.termux/files/home}"

NAZA_DIR="$HOME_T/.naza"

KEYSTORE="$PREFIX/bin/termux-keystore"

ALIAS="naza-unlock"
SIGN_ALGO="SHA256withRSA"

CHALLENGE="$NAZA_DIR/challenge"
SIGNATURE="$NAZA_DIR/signature"
TOKEN="$NAZA_DIR/unlock.token"

export LD_PRELOAD="$PREFIX/lib/libtermux-exec.so"

die() {
    echo "ERROR: $*" >&2
    rm -f \
        "$CHALLENGE" \
        "$SIGNATURE"
    exit 1
}

###############################################################################
# DIRECTORY
###############################################################################

mkdir -p "$NAZA_DIR"

[ ! -L "$NAZA_DIR" ] ||
    die ".naza is a symbolic link"

chmod 700 "$NAZA_DIR"

###############################################################################
# KEYSTORE
###############################################################################

[ -x "$KEYSTORE" ] ||
    die "termux-keystore unavailable"

###############################################################################
# POLICY CHECK
###############################################################################

STATE="$(
    "$PREFIX/bin/python" - "$KEYSTORE" <<'PY'
import json
import subprocess
import sys

ks = sys.argv[1]

items = json.loads(
    subprocess.check_output(
        [ks, "list"],
        text=True,
    )
)

for item in items:

    if item.get("alias") != "naza-unlock":
        continue

    auth = item.get("user_authentication") or {}

    good = (
        item.get("algorithm") == "RSA"
        and int(item.get("size", 0)) == 2048
        and bool(item.get("inside_secure_hardware"))
        and bool(auth.get("required"))
        and bool(auth.get("enforced_by_secure_hardware"))
        and int(
            auth.get(
                "validity_duration_seconds",
                -1
            )
        ) == 10
    )

    print(
        "CORRECT"
        if good
        else
        "WRONG"
    )

    raise SystemExit(0)

print("MISSING")
PY
)"

[ "$STATE" = "CORRECT" ] ||
    die "naza-unlock does not have the correct Gate 3 policy"

###############################################################################
# CLEAN OLD TEMPORARY FILES
###############################################################################

rm -f \
    "$CHALLENGE" \
    "$SIGNATURE"

###############################################################################
# CREATE RANDOM CHALLENGE
###############################################################################

python - <<'PY' > "$CHALLENGE"
import secrets

print(
    secrets.token_hex(32),
    end=""
)
PY

chmod 600 "$CHALLENGE"

grep -Eq \
    '^[0-9a-f]{64}$' \
    "$CHALLENGE" ||
    die "Challenge generation failed"

###############################################################################
# USER MESSAGE
###############################################################################

echo
echo "================================================================"
echo " NAZA GATE 3"
echo "================================================================"
echo
echo "Android Keystore hardware authentication is required."
echo
echo "Lock the phone."
echo "Unlock/authenticate the phone."
echo "Then continue."
echo
echo "No biometric-specific Termux API is used."
echo

###############################################################################
# ACTUAL TERMUX-KEYSTORE SIGN INTERFACE
#
# termux-keystore:
#
#   sign <alias> <algorithm> <input-file> <output-file>
#
###############################################################################

"$KEYSTORE" sign \
    "$ALIAS" \
    "$SIGN_ALGO" \
    "$CHALLENGE" \
    "$SIGNATURE" ||
    die "Android Keystore signing failed"

[ -s "$SIGNATURE" ] ||
    die "Android Keystore returned no signature"

###############################################################################
# EXISTING NAZA TOKEN FORMAT
###############################################################################

TOKEN_VALUE="$(
    python - \
        "$CHALLENGE" \
        "$SIGNATURE" \
        <<'PY'
from pathlib import Path
import hashlib
import sys

challenge = Path(
    sys.argv[1]
).read_text().strip()

signature = Path(
    sys.argv[2]
).read_bytes()

# Naza's existing token contract:
#
# SHA256(challenge text + signature bytes)
#
# The resulting token is 64 lowercase hexadecimal characters.

digest = hashlib.sha256()

digest.update(
    challenge.encode("ascii")
)

digest.update(
    signature
)

token = digest.hexdigest()

if len(token) != 64:
    raise SystemExit(
        "Unexpected token length"
    )

print(token)
PY
)"

printf '%s\n' "$TOKEN_VALUE" |
    grep -Eq \
        '^[0-9a-f]{64}$' ||
    die "Generated token does not match Naza token format"

###############################################################################
# ATOMIC TOKEN INSTALL
###############################################################################

TMP_TOKEN="$(
    mktemp "$NAZA_DIR/.unlock.token.XXXXXX"
)"

chmod 600 "$TMP_TOKEN"

printf '%s\n' "$TOKEN_VALUE" > "$TMP_TOKEN"

mv -f \
    "$TMP_TOKEN" \
    "$TOKEN"

chmod 600 "$TOKEN"

###############################################################################
# CLEAN CHALLENGE/SIGNATURE
###############################################################################

rm -f \
    "$CHALLENGE" \
    "$SIGNATURE"

unset TOKEN_VALUE

echo
echo "Gate 3 Android Keystore authentication: PASS"
echo "Naza unlock token ready."
echo "Token: $TOKEN"
echo

