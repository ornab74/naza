# SpookyNaza tri-hybrid

New keys and key rotations default to NKEY4: SpookyCombiner-1
(ML-KEM-1024 + HQC-256) combined with an independent X25519 exchange,
with HKDF-SHA512 and AES-256-GCM. ML-KEM is the standardized Kyber-derived
KEM defined by [NIST FIPS 203](https://csrc.nist.gov/pubs/fips/203/final).
AES-GCM is the authenticated payload cipher, not a third KEM.

This is an experimental local envelope construction, not a standardized or
independently reviewed hybrid protocol. Possession of the external protector
allows recovery of the stored private keys: the envelope does not provide
forward secrecy or protection against compromise of that protector.
Machine-only mode retains the existing hardware-derived gate; use a passphrase
for a secret gate. Python does not guarantee secret erasure or constant timing.

## Usage and compatibility

Run `python3 main.py` or `python3 mainfood.py` with the existing application
dependencies. Install the pinned liboqs backend using the included
`install_liboqs_0.14.0.sh`; ML-KEM-1024 and HQC-256 must both be enabled.
There is no automatic downgrade if either is missing.

Existing NKEY2 and NKEY3 keys remain readable. Choose **Enable SpookyNaza
tri-hybrid** to authenticate and rewrap the current data key without changing
model/chat ciphertext. Supply the current passphrase or token for a gated key.
The new envelope is opened and compared before the atomic replacement.
The existing isolated SpookyCombiner-1 Research Lab remains available.
Explicit API callers can retain the classical writer with
`save_wrapped_key(key, passphrase, mode="classical")`.

## Envelope

`NKEY4 | version (1 byte) | flags (1 byte) | salt (16 bytes) | SPK3 envelope`

SPK3 carries a length-prefixed SPK1 envelope protecting a fresh 32-byte seed,
both X25519 public keys, a protector-sealed X25519 private key, and the
AES-GCM payload. Its transcript binds the suite, outer header, complete SPK1
envelope, and public keys. Separately labeled HKDF lanes combine the recovered
Spooky seed and X25519 shared secret. Private-key sealing uses a separate key
and nonce; payload associated data also authenticates the sealed private key.
The parser bounds lengths and rejects trailing data, altered headers, and
missing branches. Open errors are generic; this is not a timing guarantee.

## Verification

```
python3 test_spooky_combiner.py
python3 -m unittest -v test_spooky_trihybrid
python3 -m py_compile main.py mainfood.py spooky_trihybrid.py
```

The structural suite uses fake PQ KEMs with real X25519, HKDF, and AES-GCM.
It covers round trips, component tampering, truncation, appended bytes, context
binding, wrong protectors, unavailable PQ backends, the default writer, and
preservation of an existing key when creation fails. These tests do not establish
cryptographic security. A real backend smoke check, when liboqs is installed:

```
python3 -c 'import os, oqs, spooky_trihybrid as t; k=os.urandom(32); p=os.urandom(32); assert t.open_envelope(t.create_envelope(p,k,oqs),k,oqs)==p'
```

## Installed environment

liboqs **0.14.0** is installed in `.local/liboqs-0.14.0`, with only
ML-KEM-1024 and HQC-256 enabled and `OQS_USE_OPENSSL=OFF` (bundled routines).
The project `.venv` contains liboqs-python **0.12.0**, pinned to upstream commit
`7906e7879a099fa34217035957d977314f99757d`. Upstream has no 0.14.0 wrapper
release. The version-mismatch warning is retained; the real-backend Spooky
self-test and all five tri-hybrid regression tests pass with this pairing.

From the project root:

```bash
source ./activate_spooky.sh
python test_spooky_real.py
```

Activation selects the project's Python environment and sets `OQS_INSTALL_PATH`.
No system Python installation or shell profile was modified.

## Verified rotation and recovery

**Rekey / Rotate key** now authenticates the current key and either retains its
gate or applies a new nonempty passphrase. It generates a fresh NKEY4 key,
authenticates existing model/chat ciphertext and any MACs, encrypts and opens
staged replacements, and updates both MAC files. Plaintext is held in memory;
rotation no longer creates plaintext temporary files.

Encrypted backups and replacements are staged privately in `.naza-rotation`.
A durable journal records the fixed target set before replacement. At startup,
Naza restores the old set if replacement was interrupted, or preserves the new
set if its commit marker was written. Recovery is repeatable. If rollback cannot
finish, the application exits and retains the journal for the next startup.
Do not delete this directory while recovery is pending. Completed backups are
removed normally; this does not promise physical erasure on SSDs or snapshots.

Private writes now flush complete buffered output, sync the file, replace it,
and sync its parent directory. Rotation uses a POSIX advisory lock; run only one
Naza application against a data directory, since ordinary chat/model operations
do not share this rotation lock. These are recoverable multi-file updates, not
an atomic snapshot visible to concurrent readers. Large files still require
memory for whole-file AES-GCM and disk space for encrypted backups and staging.

The **Encryption status** menu reads the active key format and gate directly.
It displays the default suite and available PQ backend without exposing keys.

Regression checks:

```bash
source ./activate_spooky.sh
python -m unittest -v test_naza_storage test_naza_rotation test_spooky_trihybrid
python test_spooky_real.py
```

Storage tests include actual subprocess termination before/after the commit
marker, recovery idempotence, write failures, invalid journal targets, and
private file permissions. The real-backend runner now also tests successful
rotation and rejection of corrupt ciphertext/MACs without replacing live data.
