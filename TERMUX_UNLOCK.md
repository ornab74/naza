# Native Termux Gate 3 unlock

Naza now runs directly in **native Termux**. The older guest-runtime launch path and biometric-specific Termux API are not part of Gate 3.

Gate 3 uses an Android Keystore RSA-2048 key named `naza-unlock`. Setup verifies that the alias is inside secure hardware, requires Android user authentication, is hardware-enforced, and has a 10-second authorization validity window.

## Unlock flow

Run:

```bash
bash ~/naza/naza_unlock.sh
```

The helper creates a fresh random 256-bit challenge, asks `termux-keystore` to sign it with `SHA256withRSA`, and derives the existing 64-character Naza token from `SHA256(challenge || signature)`. Challenge/signature files are owner-only and removed after use; the token is atomically installed as `~/.naza/unlock.token` with mode `0600`.

Authentication is enforced by the Android Keystore policy attached to the non-exportable hardware-backed key. No separate biometric-specific Termux command is required.

Then start Naza:

```bash
bash ~/naza/run_naza.sh
```

## Trust boundary

The hardware key is non-exportable, but the derived token exists inside the Termux UID while Naza starts. Naza adds owner-only files, process hardening, runtime permission checks, and authenticated encrypted storage. These measures improve local resistance; they do not make a fully compromised Android/Termux UID harmless.
