# Naza — native Termux secure local LLM + environmental risk research

Naza is a local encrypted LLM CLI/TUI with road and food/water environmental scanning, encrypted model/history storage, experimental entropy-derived signals, and the **SpookyNaza** post-quantum research key path.

> **Research / decision-support warning:** Naza is not a certified safety instrument. Low/Medium/High classifications are not proof that a road, food, water source, device, or environment is safe or unsafe. Use direct observation, trusted measurements, appropriate testing, and professional/emergency guidance for consequential decisions.

![Naza SecureLLM TUI](https://raw.githubusercontent.com/ornab74/naza/refs/heads/main/demonaza.png)

## Current Android build: native Termux

The supported Android environment is **native Google Play Termux on Android 15 / API 35 / aarch64**. The older Ubuntu guest runtime is retired, and Naza does not use a biometric-specific Termux API for Gate 3.

Gate 3 is implemented with a **hardware-backed Android Keystore key** through `termux-keystore`. Naza uses an RSA-2048 `naza-unlock` alias configured for Android user authentication with a 10-second validity window. The unlock helper signs a fresh random challenge and derives Naza's short-lived 64-hex token from that signature. See [`TERMUX_UNLOCK.md`](TERMUX_UNLOCK.md).

### Install or reconcile an existing build

```bash
pkg update -y
pkg install -y git
git clone https://github.com/ornab74/naza.git
cd naza
bash install-native-termux-repair.sh
```

The installer is reconciliation-oriented: it preserves `.enc_key`, encrypted chat history, models, and private runtime data; it does **not** automatically rekey Naza.

After setup:

```bash
bash ~/naza/naza_unlock.sh
bash ~/naza/run_naza.sh
```

## Dependency cleanup

`psutil` and PennyLane are no longer runtime dependencies. Metrics come directly from `/proc` and `/sys`; Naza's entropy/entanglement-inspired signal uses its in-house small statevector implementation.

The native dependency set is pinned in `requirements.in` / `requirements.txt`. The old scientific stack that came with PennyLane (`pennylane-lightning`, `rustworkx`, `scipy`, and `scipy-openblas32`) is intentionally absent from the Android runtime.

## Cryptographic architecture

New keys and rotations default to **NKEY4 / SpookyNaza tri-hybrid**:

```text
SpookyCombiner-1: ML-KEM-1024 + HQC-256
                 + independent X25519 lane
HKDF-SHA512
AES-256-GCM
```

The implementation is in `spooky_combiner.py` and `spooky_trihybrid.py`. The native liboqs backend is pinned to **0.14.0**; the Python wrapper is pinned to upstream commit `7906e7879a099fa34217035957d977314f99757d`. Both `ML-KEM-1024` and `HQC-256` are required.

SpookyCombiner-1 and the tri-hybrid envelope are **experimental Naza research constructions**, not NIST-standardized protocols and not independently cryptanalyzed. Transcript binding, domain-separated HKDF lanes, AEAD, strict parsing and generic authentication failures are implementation hardening—not a substitute for formal analysis or third-party review. See [`SPOOKY_COMBINER_RESEARCH.md`](SPOOKY_COMBINER_RESEARCH.md) and [`SPOOKY_TRIHYBRID.md`](SPOOKY_TRIHYBRID.md).

## Native runtime hardening

The current path uses:

- `umask 077` and owner-only sensitive files;
- Android Keystore hardware-auth Gate 3;
- `libtermux-exec.so` only for native Termux executable compatibility, never a libpython preload;
- process non-dumpability and `no_new_privs` enforcement at normal launch;
- private atomic storage and recoverable encrypted-file replacement;
- pinned/digest-verified liboqs source;
- startup crypto preflight and syntax/smoke checks.

## Environmental/scanner concepts

The unified `main.py` includes Road Scanner and Food/Water Scanner modes. Prompts combine user observations with local system/environmental metrics and Naza's experimental entropy-derived signal.

That entropy signal is a **software-derived heuristic feature**, not a physical quantum sensor. The in-house statevector path replaces the old PennyLane dependency while retaining the research concept: observables, correlation terms, and a reduced-state von Neumann entropy contribution are computed internally.

## Main files

- `main.py` — unified TUI, scanners, encrypted storage integration, key workflows, research lab.
- `install-native-termux-repair.sh` — native Termux install/reconciliation path.
- `naza_unlock.sh` — Android Keystore Gate 3 challenge/sign/token helper.
- `run_naza.sh` — hardened native launcher.
- `naza_storage.py` — private atomic writes, locking, rotation journal/recovery.
- `install_liboqs_0.14.0.sh` — pinned and digest-verified OQS build helper.
- `spooky_combiner.py` — experimental ML-KEM-1024 + HQC-256 combiner.
- `spooky_trihybrid.py` — combiner + X25519 NKEY4 envelope.

## Validation

```bash
python -m py_compile main.py naza_storage.py spooky_combiner.py spooky_trihybrid.py
bash -n install-native-termux-repair.sh
bash -n naza_unlock.sh
bash -n run_naza.sh
python -m unittest discover -s tests -v
```

Existing NKEY2/NKEY3 material remains readable. NKEY4 is the default for new/rotated keys. Setup never silently migrates or rekeys existing encrypted data.

## License

See [`LICENSE`](LICENSE).
