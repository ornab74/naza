# Native Termux Gate 3 unlock

Naza now runs directly in **native Termux**. The old Ubuntu/PRoot launch path and the `termux-fingerprint` API are not part of the runtime.

Gate 3 uses an Android Keystore RSA-2048 key named `naza-unlock`. The installer verifies that the key is inside secure hardware, requires Android user authentication, is hardware-enforced, and has a 10-second authorization validity window. If the alias exists with the wrong policy, the repair installer may recreate **only** that alias; it never automatically rekeys Naza's `.enc_key` or encrypted data.

## Unlock flow

Run:

```bash
bash ~/naza/naza_unlock.sh
```

The helper creates a fresh random 256-bit challenge, asks `termux-keystore` to sign it with `SHA256withRSA`, and derives the existing 64-character Naza token from `SHA256(challenge || signature)`. Challenge and signature temporary files are owner-only and removed after use; the resulting token is written atomically as `~/.naza/unlock.token` with mode `0600`.

No fingerprint-specific Termux API call is used. Authentication is enforced by the Android Keystore policy attached to the hardware-backed key, so the Android device may prompt for the authentication method allowed by the device/key policy.

Then start Naza with:

```bash
bash ~/naza/run_naza.sh
```

or use the boot helper installed by the repair script.

## Trust boundary

The hardware key is non-exportable, but the short-lived derived token exists in the Termux UID while Naza is starting. The launcher applies process hardening where supported (`PR_SET_DUMPABLE=0`, `PR_SET_NO_NEW_PRIVS=1`), owner-only files/directories, and rejects unsafe runtime ownership/permissions. This improves local resistance; it is not a claim that a fully compromised Android/Termux UID can be made harmless.
