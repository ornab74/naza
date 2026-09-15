# Naza orbital conditioning simulation

Naza includes a passive orbital-conditioning lane for scanner robustness tests. The bundled `Optus-X-positioning.csv` is used as the calibration anchor for a deterministic propagator in `naza_orbit_sim.py`.

## Threat-model meaning

For the test harness, assume an adversarial external nuisance source is correlated with the simulated orbital state. This is a **software robustness assumption**, not an assertion that the orbit data prove an attack. Naza does not transmit, jam, spoof, or target a spacecraft or radio link.

The orbital lane is also **not cryptographic entropy**. Anyone with the same orbital model and timestamp can reproduce it.

## Simulation model

The propagator uses:

- launch date metadata: 2024-11-17;
- 688 km perigee altitude;
- 706 km apogee altitude;
- 97.4 degree inclination;
- first-row RAAN, argument of perigee, and mean anomaly from the bundled CSV as the calibration epoch;
- two-body Kepler propagation plus first-order J2 secular drift;
- WGS-84 ECI -> ECEF -> geodetic conversion.

`naza_crypto_preflight.py` checks that the propagator reproduces the supplied calibration row to the CSV's published rounding precision before normal launch.

This gives an exact state **inside this simulation model**. It is not a guarantee of a real spacecraft's physical position without independently verified current orbit elements/telemetry.

## Position quantum state

`main.py` encodes six bounded simulated-position features into Naza's in-house statevector engine:

1. latitude sine;
2. latitude cosine;
3. longitude sine;
4. longitude cosine;
5. orbital phase;
6. normalized altitude within the modeled 688-706 km band.

A six-qubit statevector receives position-dependent RY/RZ rotations and two entangling passes. Naza derives a cut entropy, pairwise tension, and a bounded `orbit_q_entropy` score.

The orbit score feeds only an integrity-conditioning lane. Its correction to the host entropy score is capped at +/-0.08, so orbital position cannot silently become a direct food/road risk-label input.

## Scanner prompt behavior

Every Road or Food/Water scan receives both:

- the normal host-derived quantum/statevector metrics; and
- the simulated position-derived quantum/statevector metrics.

The prompt explicitly tells the model that the position state exists to model and detune an orbit-correlated nuisance source under the test assumption. It also forbids changing the Low/Medium/High label solely because of orbital position.

The prompt includes three data-quality practices:

1. timestamp and calibrate direct local sensors at acquisition;
2. cross-check important local scene facts using independent modalities;
3. maintain before/during/after orbital-phase baseline windows and compare residuals.

These practices can improve coherence and measurement quality, but they cannot guarantee perfect accuracy.

## TUI simulation surface

The main menu contains **Orbit Conditioning Simulation**. It displays the current simulated state and the derived position-state quantum metrics and can export a two-hour, one-minute-resolution CSV as `naza_orbit_sim_current.csv`.

A snapshot generated for this bundle is included as `simulated-orbit-current.csv`.
