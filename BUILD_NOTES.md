# Naza native Termux update bundle

This bundle is prepared for native Termux and is not a PRoot build.

Key installer/runtime properties:

- preserves existing `.enc_key`, encrypted history, models, and private working data;
- removes runtime dependence on PennyLane and psutil;
- uses Android Keystore Gate 3 hardware-backed authorization without `termux-fingerprint`;
- builds liboqs 0.14.0 with one build job and a minimal mechanism set containing only ML-KEM-1024 and HQC-256;
- validates both KEMs with real encapsulation/decapsulation round trips;
- builds llama-cpp-python 0.3.1 from source with one CMake job for native Termux;
- locates packaged `libllama.so`, exports `LLAMA_CPP_LIB_PATH`, validates direct dynamic loading, then validates the Python API;
- launches offline by default and strips proxy variables; a trusted model-download maintenance session requires explicit `NAZA_OFFLINE_MODE=0`;
- validates cryptography, SpookyNaza tri-hybrid round-trip/tamper rejection, and Python/shell syntax before declaring repair complete.

Validation performed while packaging:

- `python -m py_compile` on the Python runtime modules;
- `bash -n` on installer, launcher, and unlock scripts;
- `tests/test_native_bundle.py`: 6/6 tests passed.

The passive resilience changes are designed to reduce dependence on external connectivity and reject corrupted or incorrectly linked runtime components. They do not transmit, jam, spoof, or target radio/satellite systems.

## Orbital conditioning repair

- Added `naza_orbit_sim.py`, calibrated from the bundled positioning CSV.
- Reproduces the supplied calibration row using Kepler propagation + first-order J2 drift.
- Added a six-qubit deterministic position-state circuit to `main.py`.
- Position state is a bounded nuisance-conditioning lane only; correction is capped at +/-0.08.
- Rebuilt Road/Food scanner prompt so the correct surface fields are used.
- Prompt now documents the adversarial orbit-correlated poisoning **test assumption**, the purpose of the position state, and three local-data quality practices.
- Added an Orbit Conditioning Simulation TUI surface and CSV export.
- Launcher now requires the calibrated CSV and exports `NAZA_ORBIT_SOURCE_CSV` to preflight/runtime.
- Preflight verifies the simulator against the supplied CSV calibration row.
