# Naza — native Termux secure local LLM + environmental risk research

Naza is a local encrypted LLM CLI/TUI with road and food/water environmental scanning, encrypted model/history storage, experimental entropy-derived signals, and the **SpookyNaza** post-quantum research key path.

> **Research / decision-support warning:** Naza is not a certified safety instrument and its Low/Medium/High classifications are not proof that a road, food, water source, device, or environment is safe or unsafe. Use direct observation, trusted measurements, appropriate testing, and professional/emergency guidance for consequential decisions.

![Naza SecureLLM TUI](https://raw.githubusercontent.com/ornab74/naza/refs/heads/main/demonaza.png)

## Current build: native Termux

The supported Android environment is now **native Google Play Termux on Android 15 / API 35 / aarch64**. The previous Ubuntu/PRoot runtime and `termux-fingerprint` API path are retired.

Security Gate 3 remains, but it is implemented with a **hardware-backed Android Keystore key** through `termux-keystore`. Naza verifies an RSA-2048 `naza-unlock` alias with hardware-enforced user authentication and a 10-second authorization validity window, then derives Naza's short-lived 64-hex unlock token from a freshly signed random challenge. See [`TERMUX_UNLOCK.md`](TERMUX_UNLOCK.md).

### Install / reconcile an existing build

```bash
pkg update -y
pkg install -y git
git clone https://github.com/ornab74/naza.git
cd naza
bash install-native-termux-repair.sh
```

The repair installer is intentionally reconciliation-oriented: it discovers and reuses working components, backs up files before repair, preserves `.enc_key`, encrypted chat history, models, and private temporary storage, and **never automatically rekeys Naza**.

After installation:

```bash
bash ~/naza/naza_unlock.sh
bash ~/naza/run_naza.sh
```

## Dependency cleanup

`psutil` and PennyLane are no longer used. Runtime metrics are read directly from `/proc` and `/sys`, and the entropy/entanglement-inspired score uses Naza's in-house small statevector implementation. The native dependency set is pinned in `requirements.in` / `requirements.txt` and mirrored by the reconciliation installer.

The native build intentionally avoids Android-hostile scientific stacks that were previously pulled in indirectly (`pennylane`, `pennylane-lightning`, `rustworkx`, `scipy`, `scipy-openblas32`, and `psutil`).

## Cryptographic architecture

New keys and rotations default to **NKEY4 / SpookyNaza tri-hybrid**:

```text
SpookyCombiner-1: ML-KEM-1024 + HQC-256
                 + independent X25519 lane
HKDF-SHA512
AES-256-GCM
```

The implementation is in `spooky_combiner.py` and `spooky_trihybrid.py`. The liboqs backend is pinned to **0.14.0** and the Python wrapper to upstream commit `7906e7879a099fa34217035957d977314f99757d`; the installer requires both `ML-KEM-1024` and `HQC-256` to be present.

SpookyCombiner-1 and the tri-hybrid envelope are **experimental Naza research constructions**, not NIST-standardized protocols and not independently cryptanalyzed. The code uses transcript binding, domain-separated HKDF lanes, AES-256-GCM, key confirmation, strict parsing/length limits, generic authentication failures, and best-effort secret zeroization, but those properties do not substitute for formal analysis or third-party review. See [`SPOOKY_COMBINER_RESEARCH.md`](SPOOKY_COMBINER_RESEARCH.md) and [`SPOOKY_TRIHYBRID.md`](SPOOKY_TRIHYBRID.md).

## Native runtime hardening

The current launcher/install path includes:

- owner-only Naza directories and sensitive files (`umask 077`);
- Android Keystore hardware-auth Gate 3, without a fingerprint-specific API;
- `libtermux-exec.so` only where native Termux executable compatibility requires it, with no libpython preload;
- process non-dumpability and `no_new_privs` enforcement for normal Naza launch;
- runtime ownership/permission checks for Python and liboqs;
- atomic durable storage helpers and recoverable encrypted-file rotation;
- pinned/verified liboqs source archives and pinned liboqs-python source;
- validation of ML-KEM-1024, HQC-256, X25519, HKDF-SHA512, AES-256-GCM, Python syntax, shell syntax, and the Gate 3 token contract.

## Environmental / scanner concepts

The unified `main.py` includes Road Scanner and Food/Water Scanner modes. Scanner prompts combine user observations with locally collected system/environmental metrics and Naza's experimental entropy-derived signal. That signal is a software-derived heuristic feature; it is **not a physical quantum sensor** and should not be represented as one.

The current in-house statevector path replaces the old PennyLane dependency and computes observables and a reduced-state von Neumann entropy term internally. This keeps the concept researchable while removing the heavyweight quantum-simulation dependency from the Android runtime.

### Orbital conditioning robustness layer

`naza_orbit_sim.py` adds a deterministic orbital simulation lane calibrated from the bundled `Optus-X-positioning.csv`. Under the scanner **test assumption** that an adversarial external nuisance source is correlated with orbital position, `main.py` builds a separate six-qubit position state from latitude/longitude geometry, orbital phase, and normalized altitude. Its entropy/tension result is used only to detune scanner-integrity confidence through a correction capped at +/-0.08; orbital coordinates are explicitly forbidden from directly deciding the food/road label.

The main menu includes an **Orbit Conditioning Simulation** surface that shows the simulated live state and can export a fresh two-hour ephemeris. The bundled `simulated-orbit-current.csv` is a snapshot generated from the same propagator. These values are deterministic simulation features, **not cryptographic entropy and not verified real-time spacecraft telemetry**. See [`ORBIT_CONDITIONING.md`](ORBIT_CONDITIONING.md).

## Main files

- `main.py` — unified TUI, scanners, encrypted storage integration, key workflows, research lab.
- `naza_orbit_sim.py` — CSV-calibrated deterministic orbital propagator used by the scanner robustness layer.
- `Optus-X-positioning.csv` — supplied simulation calibration ephemeris.
- `simulated-orbit-current.csv` — regenerated simulation snapshot included with this bundle.
- `install-native-termux-repair.sh` — native Termux discovery/repair/reconciliation installer.
- `naza_unlock.sh` — Android Keystore Gate 3 challenge/sign/token helper.
- `run_naza.sh` — hardened native launcher.
- `naza_storage.py` — private atomic writes, locking, rotation journal/recovery.
- `install_liboqs_0.14.0.sh` — pinned and digest-verified OQS build helper.
- `spooky_combiner.py` — experimental ML-KEM-1024 + HQC-256 combiner.
- `spooky_trihybrid.py` — combiner + X25519 NKEY4 envelope.

## Validation

Useful local checks:

```bash
python -m py_compile main.py naza_orbit_sim.py naza_storage.py spooky_combiner.py spooky_trihybrid.py
python naza_orbit_sim.py --verify-source
bash -n install-native-termux-repair.sh
bash -n naza_unlock.sh
bash -n run_naza.sh
python -m unittest discover -s tests -v
```

For a real OQS backend smoke test, first activate/configure the native environment and ensure `OQS_INSTALL_PATH` points to the installed liboqs 0.14.0 prefix.

## Compatibility

Existing NKEY2/NKEY3 material remains readable by the application. NKEY4 is the default for new/rotated keys. The repair installer preserves existing encrypted data and does not silently migrate/rekey it.

## License

See [`LICENSE`](LICENSE).


## Native Termux resilience notes

The native launcher is offline-by-default (`NAZA_OFFLINE_MODE=1`) and strips proxy environment variables before starting Naza. This prevents an ordinary launch from silently depending on external connectivity or network-provided model bytes. To perform a deliberate trusted model download, launch that maintenance session with `NAZA_OFFLINE_MODE=0`; model SHA-256 verification still remains mandatory.

`llama-cpp-python==0.3.1` is built from source with one CMake build job on Termux. The installer locates the packaged `libllama.so`, exports `LLAMA_CPP_LIB_PATH`, adds the library directory to `LD_LIBRARY_PATH`, performs a direct `ctypes` load, and only then accepts the Python import. This specifically catches the Android failure mode where the package exists but the native library cannot be resolved.

liboqs 0.14.0 is built with a single compile job and `OQS_MINIMAL_BUILD` restricted to `KEM_ml_kem_1024;KEM_hqc_256`; examples/tests and unrelated mechanisms are not built. The installer performs real encapsulation/decapsulation round trips for both KEMs before accepting the backend.
