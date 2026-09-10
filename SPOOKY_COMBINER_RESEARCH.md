# SpookyCombiner-1 — Naza research implementation

> **EXPERIMENTAL. NOT NIST STANDARDIZED OR VALIDATED. DO NOT USE AS A PRODUCTION SECURITY CLAIM.**

SpookyCombiner-1 is an invented Naza research construction combining **ML-KEM-1024** and **HQC-256**. Its purpose is to study heterogeneous post-quantum KEM composition and failure behavior, not to replace standardized protocols.

## Construction

Each branch generates an independent liboqs KEM key pair and performs encapsulation. The two shared secrets are individually extracted with HKDF-SHA512 using branch-specific labels and a canonical transcript. The extracted lanes are concatenated into a second HKDF-SHA512 stage. Independent 256-bit keys are then derived for AES-256-GCM data wrapping and HMAC-SHA512 key confirmation.

The transcript commits to the version, exact suite name, application context, random envelope identifier, fixed algorithm order, both public keys, and both KEM ciphertexts. The parser requires exactly two branches in the fixed order `ML-KEM-1024`, `HQC-256`; removing or substituting a branch is rejected as a downgrade.

Exported KEM secret keys are not stored in plaintext. Each is independently sealed with AES-256-GCM under an external 256-bit protector using a branch-specific HKDF key and transcript-bound associated data. In Naza's integrated lab, the protector is machine-bound and is used only for disposable random canaries.

## Failure handling

Decapsulation/decryption errors inside an individual branch do not produce branch-specific user errors. The implementation derives a deterministic transcript-bound rejection secret for the failed branch and continues to the final confirmation/AEAD decision. The public API reports a single generic authentication failure.

This is an attempt to reduce obvious branch-error oracles. It is **not a constant-time guarantee**: CPython, the Python allocator, `cryptography`, and the liboqs wrapper are outside this module's timing and memory-erasure control.

## Naza integration boundary

The TUI adds **SpookyCombiner-1 Research Lab**. It can run a fresh self-test, create a stored machine-bound canary envelope, verify it, benchmark a create/open cycle, and securely delete the lab artifact.

The lab deliberately **does not wrap Naza's live data key**. The separate NKEY4 SpookyNaza tri-hybrid path now uses this combiner alongside X25519 for live key wrapping and is the default for new keys and rotations. NKEY3 remains readable. See [SpookyNaza tri-hybrid](SPOOKY_TRIHYBRID.md) for the construction and experimental limitations.

## Installer changes

The pinned liboqs 0.14.0 build now enables both `ML-KEM` and `HQC`; the Python wrapper is pinned to the upstream 0.12.0 commit (no 0.14.0 wrapper release exists). This pairing passes the real-backend envelope tests but emits a version-mismatch warning. HQC is disabled by default in upstream liboqs 0.14.0, so the Naza build explicitly enables it.

## Hardening properties implemented

- fixed two-algorithm suite and exact ordering;
- canonical transcript and explicit domain separation;
- independent lane extraction and final combiner extraction;
- independent wrap and confirmation keys;
- AES-256-GCM authenticated encryption;
- HMAC-SHA512 key confirmation with `compare_digest`;
- independent transcript-bound sealing of exported KEM secret keys;
- implicit-rejection-style fallback at the wrapper/error layer;
- strict JSON schema, base64 validation, and length caps;
- generic authentication failure path;
- private file creation inherited from Naza's atomic `0600` writer;
- best-effort zeroization of mutable secret buffers;
- tamper, wrong-protector, and downgrade structural tests.

## What has *not* been proven

There is no reduction proof establishing this exact combiner as robust under every malicious-key or chosen-ciphertext model. It has not undergone third-party cryptanalysis, interoperability review, side-channel evaluation, formal verification, or NIST validation. The self-tests establish implementation consistency and tamper rejection only; they do not establish cryptographic security.
