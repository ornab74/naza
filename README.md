# Naza — native Termux secure local LLM + environmental risk research

Naza is a local encrypted LLM CLI/TUI with road and food/water environmental scanning, encrypted model/history storage, experimental entropy-derived signals, and the **SpookyNaza** post-quantum research key path.

> **Research / decision-support warning:** Naza is not a certified safety instrument. Low/Medium/High classifications are not proof that a road, food, water source, device, or environment is safe or unsafe. Use direct observation, trusted measurements, appropriate testing, and professional/emergency guidance for consequential decisions.

![Naza SecureLLM TUI](https://raw.githubusercontent.com/ornab74/naza/refs/heads/main/demonaza.png)

## Supported build: native Termux

The supported Android environment is native Google Play Termux on Android 15 / API 35 / aarch64. The old Ubuntu/PRoot runtime and fingerprint-specific Termux API path are retired.

Gate 3 uses a hardware-backed Android Keystore key through `termux-keystore`. Naza verifies an RSA-2048 `naza-unlock` alias with hardware-enforced user authentication and a 10-second authorization window, then derives the short-lived unlock token from a freshly signed random challenge. See `TERMUX_UNLOCK.md`.

### Install / reconcile

```bash
pkg update -y
pkg install -y git
git clone https://github.com/ornab74/naza.git
cd naza
bash install-native-termux-repair.sh
```

The repair path preserves existing `.enc_key`, encrypted history, models, and application data. It does not automatically rekey Naza.

After installation:

```bash
bash ~/naza/naza_unlock.sh
bash ~/naza/run_naza.sh
```

## Android llama-cpp-python repair

`llama-cpp-python==0.3.1` is built from source with a single CMake build job when the existing installation cannot be loaded. The installer:

- locates the package-local `libllama.so`;
- exports `LLAMA_CPP_LIB_PATH` to that native library directory;
- adds the directory to `LD_LIBRARY_PATH`;
- patches the 0.3.1 Android platform classification before importing the package when required;
- performs a direct `ctypes.CDLL` load before accepting the Python import;
- verifies the `llama_cpp.Llama` API in the same venv used by `run_naza.sh`.

This catches the Android failure mode where pip reports the package installed but the native shared library cannot actually be resolved.

## Minimal liboqs build

liboqs is pinned to **0.14.0** and liboqs-python to upstream commit `7906e7879a099fa34217035957d977314f99757d`. Downloads are SHA-256 verified before extraction/install.

To keep Android RAM/build pressure low, the canonical build uses:

```text
OQS_BUILD_ONLY_LIB=ON
OQS_DIST_BUILD=OFF
OQS_MINIMAL_BUILD=KEM_ml_kem_1024;KEM_hqc_256
cmake --build ... --parallel 1
```

Only the two KEMs Naza needs are accepted: **ML-KEM-1024** and **HQC-256**. Installation/preflight performs real encapsulation/decapsulation round trips for both.

## Dependency cleanup

PennyLane and psutil are not runtime dependencies. Host metrics come directly from `/proc` and `/sys`; Naza's entropy/entanglement-inspired signal uses its own small statevector implementation.

## Cryptographic architecture

New keys and rotations default to **NKEY4 / SpookyNaza tri-hybrid**:

```text
SpookyCombiner-1: ML-KEM-1024 + HQC-256
                 + independent X25519 lane
HKDF-SHA512
AES-256-GCM
```

`spooky_combiner.py` and `spooky_trihybrid.py` are experimental Naza research constructions, not standardized protocols and not independently cryptanalyzed. See `SPOOKY_COMBINER_RESEARCH.md` and `SPOOKY_TRIHYBRID.md`.

## Orbit-conditioned scanner robustness simulation

The scanner has a passive software-only robustness lane for an **adversarial orbit-correlated sensor-poisoning test assumption**. This is a threat-model input for testing; it is not evidence that an identified real spacecraft is attacking the device.

`naza_orbit_sim.py` is calibrated from the sanitized `Optus-X-positioning.csv` and propagates a deterministic two-body + first-order J2 simulation. The calibration CSV contains orbital/Earth-centered state only; observer-specific look-angle fields are not carried in this repo version.

At scan time, `naza_orbit_patch.py` creates a separate six-qubit in-house statevector from simulated latitude/longitude geometry, orbital phase, normalized altitude, and a deterministic position feature. It derives a position-state entropy/tension score and uses it only as a nuisance-conditioning lane.

The correction to host-state entropy is hard-capped at **±0.08**. Prompt rules explicitly forbid orbital latitude, longitude, altitude, phase, or `orbit_q_entropy` from directly selecting Low/Medium/High. The lane can affect scanner confidence/integrity only.

The prompt also asks the scanner to improve coherence by:

1. timestamping/calibrating direct local sensors at acquisition;
2. cross-checking important observations with independent modalities/sources;
3. maintaining before/during/after orbital-phase baselines and comparing residuals.

The main menu exposes **Orbit Conditioning Simulation**, which refreshes the current simulated state and can export a fresh two-hour CSV. Position-derived values are deterministic simulation features, **not cryptographic entropy and not verified live telemetry**.

See `ORBIT_CONDITIONING.md` and `SCANNER_PROMPT_ORBIT_LAYER.md`.

## Repository layout

- `main.py` — small hardened entrypoint; installs runtime patches then starts Naza.
- `naza_core.py` — preserved application core: TUI, scanners, encrypted storage/key workflows, research lab.
- `naza_orbit_patch.py` — bounded six-qubit position-state circuit, prompt conditioning, simulation menu surface.
- `naza_orbit_sim.py` — deterministic CSV-calibrated orbital propagator/exporter.
- `Optus-X-positioning.csv` — sanitized minimal simulation calibration ephemeris.
- `install-native-termux-repair.sh` — native Termux reconcile/install path.
- `install_liboqs_0.14.0.sh` — pinned minimal one-job OQS build helper.
- `naza_unlock.sh` — Android Keystore Gate 3 challenge/sign/token helper.
- `run_naza.sh` — hardened native launcher, offline by default.
- `naza_crypto_preflight.py` — fail-closed llama/OQS/tri-hybrid/orbit runtime checks.
- `naza_storage.py` — private atomic writes, locking, rotation journal/recovery.

## Runtime hardening

Normal launch:

- uses owner-private defaults (`umask 077`);
- uses `libtermux-exec.so` only for native Termux execution compatibility, never libpython preload;
- requires process non-dumpability / `no_new_privs` through the application hardening path;
- strips proxy environment variables and defaults to `NAZA_OFFLINE_MODE=1`;
- requires the calibrated orbital CSV to be a regular non-symlink file;
- discovers and verifies the package-local llama native library before runtime;
- runs `naza_crypto_preflight.py` before starting `main.py`.

For a deliberate trusted model-download maintenance session, set `NAZA_OFFLINE_MODE=0`; model digest verification remains required.

## Validation

Useful checks:

```bash
python -m py_compile main.py naza_core.py naza_orbit_patch.py naza_orbit_sim.py naza_crypto_preflight.py naza_storage.py spooky_combiner.py spooky_trihybrid.py
python naza_orbit_sim.py --verify-source
bash -n install-native-termux-repair.sh install_liboqs_0.14.0.sh naza_unlock.sh run_naza.sh
python -m unittest discover -s tests -v
```

Existing NKEY2/NKEY3 material remains readable. NKEY4 is the default for new/rotated keys. The repair path does not silently migrate or rekey existing encrypted data.

## License

See `LICENSE`.
