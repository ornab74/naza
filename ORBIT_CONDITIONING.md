# Naza orbital conditioning simulation

Naza includes a passive software robustness lane for an **adversarial orbit-correlated sensor-poisoning test assumption**. The assumption is useful for exercising scanner integrity behavior; it is not evidence that a real spacecraft is attacking the device.

The implementation never transmits, jams, spoofs, or targets a spacecraft/radio link.

## Simulation model

`naza_orbit_sim.py` loads the first row of `Optus-X-positioning.csv` as its calibration epoch and propagates the supplied 688 x 706 km, 97.4 degree orbit with two-body Kepler motion plus first-order J2 secular drift of RAAN, argument of perigee, and mean anomaly.

The bundled CSV is deliberately minimal and contains orbital/Earth-centered state only. Observer-specific look-angle fields are not required by the propagator.

This produces an exact state **inside this deterministic simulation model**. It is not verified real-time spacecraft telemetry; current measured orbit elements would be required for that.

## Six-qubit position state

`naza_orbit_patch.py` encodes six normalized features:

1. latitude sine;
2. latitude cosine;
3. longitude sine;
4. longitude cosine;
5. orbital phase;
6. normalized altitude.

The statevector uses position-dependent RY/RZ rotations, a ring entangling pass, and opposite-qubit entangling chords. Naza derives cut entropy, pairwise tension, and an `orbit_q_entropy` score.

The position-derived hash feature is deterministic and **must not be treated as cryptographic entropy**.

## Bounded detuning

The orbital state is a nuisance-conditioning lane only. Its contribution is capped at +/-0.08 when forming `detuned_host_entropy`. The prompt explicitly forbids changing Low/Medium/High solely because of orbital latitude, longitude, altitude, phase, or orbit entropy.

The integrity guard compares the host-state score and orbit-state score:

- GREEN: small discrepancy;
- AMBER: moderate discrepancy;
- RED: large discrepancy.

This guard is about confidence in sensor state, not proof that a physical scene is dangerous.

## Scanner prompt practices

The prompt asks the model to improve measurement coherence by:

1. timestamping/calibrating direct local sensors at acquisition;
2. cross-checking important observations with independent modalities/sources;
3. maintaining before/during/after baseline windows keyed to orbital phase and comparing residuals.

## TUI surface

The main menu includes **Orbit Conditioning Simulation**. It refreshes the simulated state and can export a two-hour, one-minute-resolution CSV as `naza_orbit_sim_current.csv`.

Use `python naza_orbit_sim.py --verify-source` to confirm that the propagator still reproduces the calibration row to its published precision.
