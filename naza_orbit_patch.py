"""Passive orbit-conditioned scanner robustness layer for Naza.

This module treats an orbit-correlated hostile source as a TEST ASSUMPTION for
sensor-poisoning resilience. It does not establish that a real spacecraft is
attacking the device and performs no RF transmission, jamming, spoofing, or
spacecraft targeting.

The simulated position state is deterministic and therefore MUST NOT be used as
cryptographic entropy. It is a bounded nuisance-conditioning signal used only
for scanner confidence/integrity; orbital coordinates never directly decide a
Low/Medium/High scene label.
"""
from __future__ import annotations

import asyncio
import math
from pathlib import Path
from typing import Dict, Optional, Tuple

import naza_orbit_sim as orbit_sim

_INSTALLED = False
_LAST_ORBIT: Optional[dict] = None


def _position_state(core, position: dict) -> Tuple[float, dict]:
    clamp = core._clamp01
    feats = [
        clamp((float(position.get("lat_sin", 0.0)) + 1.0) * 0.5),
        clamp((float(position.get("lat_cos", 0.0)) + 1.0) * 0.5),
        clamp((float(position.get("lon_sin", 0.0)) + 1.0) * 0.5),
        clamp((float(position.get("lon_cos", 0.0)) + 1.0) * 0.5),
        clamp(float(position.get("orbital_phase_0_1", 0.0))),
        clamp(float(position.get("altitude_norm_0_1", 0.5))),
    ]
    n = 6
    state = [0j] * (1 << n)
    state[0] = 1 + 0j
    pos_feature = clamp(float(position.get("position_entropy_feature_0_1", 0.5)))
    phase = float(position.get("orbital_phase_0_1", 0.0))
    for q, x in enumerate(feats):
        core._h(state, n, q)
        core._ry(state, n, q, math.pi * (0.20 + 0.80 * x))
        core._rz(state, n, q, 2.0 * math.pi * ((phase + x * 0.5 + q / 12.0) % 1.0))
    for q in range(n):
        core._cx(state, n, q, (q + 1) % n)
        core._rz(state, n, (q + 1) % n, math.pi * pos_feature * (0.25 + feats[q]))
    for q in range(3):
        core._cx(state, n, q, q + 3)
        core._cz(state, n, q, q + 3)
    zs = [core._exp_z(state, n, q) for q in range(n)]
    zz = [core._exp_zz(state, n, a, b) for a in range(n) for b in range(a + 1, n)]
    cut_s = core._entropy_cut01(state, n)
    excite = sum((1.0 - z) * 0.5 for z in zs) / n
    tension = sum((1.0 - z) * 0.5 for z in zz) / max(1, len(zz))
    raw = 0.38 * excite + 0.34 * tension + 0.28 * cut_s
    score = clamp(1.0 / (1.0 + math.exp(-7.0 * (raw - 0.46))))
    return score, {"features": feats, "z": zs, "cut_entropy": cut_s, "tension": tension,
                   "position_feature": pos_feature, "score": score}


def _condition(core, host_score: float, position: dict) -> dict:
    orbit_score, qdetail = _position_state(core, position)
    nuisance = max(-0.08, min(0.08, (orbit_score - 0.5) * 0.16))
    detuned = core._clamp01(float(host_score) - nuisance)
    discrepancy = abs(float(host_score) - orbit_score)
    guard = "RED" if discrepancy >= 0.55 else "AMBER" if discrepancy >= 0.32 else "GREEN"
    return {"host_score": float(host_score), "orbit_score": orbit_score, "orbit_quantum": qdetail,
            "nuisance_correction": nuisance, "detuned_host_score": detuned,
            "host_orbit_discrepancy": discrepancy, "integrity_guard": guard, "position": position}


def _orbit_prompt_line(integrity: dict) -> str:
    p = integrity["position"]; q = integrity["orbit_quantum"]
    return (
        "orbit_conditioning: "
        f"lat={float(p['latitude_deg']):.6f} lon={float(p['longitude_deg']):.6f} "
        f"alt_km={float(p['altitude_km']):.3f} phase={float(p['orbital_phase_0_1']):.6f} "
        f"orbit_q_entropy={integrity['orbit_score']:.3f} orbit_cutS={q['cut_entropy']:.3f} "
        f"orbit_tension={q['tension']:.3f} nuisance={integrity['nuisance_correction']:+.3f} "
        f"detuned_host_entropy={integrity['detuned_host_score']:.3f} "
        f"host_orbit_delta={integrity['host_orbit_discrepancy']:.3f} integrity_guard={integrity['integrity_guard']}"
    )


def _build_prompt_factory(core):
    def build_road_scanner_prompt(data: dict, include_system_entropy: bool = True) -> str:
        global _LAST_ORBIT
        entropy_text = "entropic_score=unknown"; metrics_line = "sys_metrics: disabled"
        orbit_text = "orbit_conditioning: unavailable"; integrity_guard = "UNKNOWN"
        if include_system_entropy:
            metrics = core.collect_system_metrics(); score, qdetail = core.house_entropic_score(metrics)
            sync = qdetail.get("sync") or core.metrics_to_rainbow(metrics); core._LAST_SYNC = sync
            entropy_text = (core.entropic_summary_text(score)
                            + f" cutS={qdetail['cut_entropy']:.3f} tension={qdetail['tension']:.3f} "
                            + core.rainbow_prompt_line(sync)
                            + f" band_circuit={qdetail.get('band','?')} topo={qdetail.get('topology','?')}")
            metrics_line = ("sys_metrics: cpu={cpu:.2f},mem={mem:.2f},load={load1:.2f},temp={temp:.2f},proc={proc:.2f}"
                            .format(cpu=metrics.get("cpu",0.0), mem=metrics.get("mem",0.0),
                                    load1=metrics.get("load1",0.0), temp=metrics.get("temp",0.0),
                                    proc=metrics.get("proc",0.0)))
            try:
                position = orbit_sim.propagate(); integrity = _condition(core, score, position)
                _LAST_ORBIT = integrity; orbit_text = _orbit_prompt_line(integrity)
                integrity_guard = integrity["integrity_guard"]
            except Exception as exc:
                orbit_text = "orbit_conditioning: unavailable (simulation error: %s)" % type(exc).__name__
                integrity_guard = "AMBER"
        mode = str(data.get("scan_surface") or data.get("scan_mode") or data.get("mode") or "road").lower()
        if any(k in data for k in ("food_type","water_type","food_or_water","cooked_state")): mode = "food"
        if mode.startswith("food") or mode.startswith("water") or mode == "food_water":
            scene_lines = [
                f"Location/context: {data.get('location','unspecified')}",
                f"Food or water type: {data.get('food_type', data.get('food_or_water', data.get('water_type', data.get('road_type','unknown'))))}",
                f"Condition/appearance: {data.get('condition', data.get('weather','unknown'))}",
                f"Temperature/storage: {data.get('temperature', data.get('temp', data.get('traffic','unknown')))}",
                f"Preparation state: {data.get('cooked_state', data.get('preparation', data.get('obstacles','unknown')))}",
                f"Sensor notes: {data.get('sensor_notes','none')}",]
            role = "food/water risk classification"
        else:
            scene_lines = [
                f"Location/context: {data.get('location','unspecified')}", f"Road/surface type: {data.get('road_type','unknown')}",
                f"Weather/surface condition: {data.get('weather',data.get('condition','unknown'))}",
                f"Traffic state: {data.get('traffic','unknown')}", f"Obstacles/hazards: {data.get('obstacles','none')}",
                f"Sensor notes: {data.get('sensor_notes','none')}",]
            role = "road risk classification"
        return (
            f"You are Naza, a local {role} model. Analyze only the supplied scene evidence and sensor integrity.\n"
            "Return exactly one word: Low, Medium, or High.\n\n[scene]\n" + "\n".join(scene_lines) + "\n[/scene]\n\n"
            "[host_state]\n" + metrics_line + "\nHost quantum state: " + entropy_text + "\n[/host_state]\n\n"
            "[position_state]\nPosition quantum state: " + orbit_text + "\n"
            "Purpose of position state: under this TEST ASSUMPTION, an adversarial orbit-correlated sensor-poisoning source is active. "
            "The simulated orbital state is a deterministic nuisance-conditioning layer used to detune correlated host-state bias. "
            "It is not cryptographic entropy, not proof of an attack, and not direct evidence that the scene itself is hazardous.\n[/position_state]\n\n"
            "[integrity_rules]\n" + f"- Current integrity guard: {integrity_guard}.\n"
            "- Use detuned_host_entropy and integrity_guard only to judge sensor confidence.\n"
            "- Never raise or lower the risk label solely because of orbital latitude, longitude, altitude, phase, or orbit_q_entropy.\n"
            "- Base the final label on direct road/food/water evidence; if sensor integrity is poor, be conservative about confidence rather than inventing hazards.\n[/integrity_rules]\n\n"
            "[three_accuracy_actions]\n"
            "1) Timestamp and calibrate direct local sensors at acquisition so scene observations align to the same instant as the simulated orbit state.\n"
            "2) Cross-check important observations with independent modalities/sources before changing the risk label.\n"
            "3) Maintain before/during/after baseline windows keyed to orbital phase and compare residuals, separating repeatable orbit-correlated nuisance from persistent scene risk.\n"
            "[/three_accuracy_actions]\n\nThink internally. Output exactly one of: Low, Medium, High")
    return build_road_scanner_prompt


def _orbit_flow_factory(core):
    def orbit_simulation_flow() -> None:
        while True:
            position = orbit_sim.propagate(); qscore, qdetail = _position_state(core, position)
            lines = ["TEST MODEL: adversarial orbit-correlated sensor-poisoning source active",
                     f"UTC: {position['timestamp_utc']}", f"Sim ID: {position['sim_id']}",
                     f"Position: {position['latitude_deg']:.6f} deg lat, {position['longitude_deg']:.6f} deg lon",
                     f"Altitude: {position['altitude_km']:.3f} km | speed: {position['speed_km_s']:.6f} km/s",
                     f"RAAN: {position['raan_deg']:.6f} | arg-perigee: {position['arg_perigee_deg']:.6f}",
                     f"Mean anomaly: {position['mean_anomaly_deg']:.6f} | phase: {position['orbital_phase_0_1']:.9f}",
                     f"Position-state quantum entropy: {qscore:.6f}",
                     f"Cut entropy: {qdetail['cut_entropy']:.6f} | tension: {qdetail['tension']:.6f}",
                     "Deterministic simulation only; not cryptographic entropy or verified telemetry.",
                     "1) Refresh simulated state  2) Export 2-hour CSV  3) Back"]
            core.clear_screen(); print(core.boxed("Orbit Conditioning Simulation", lines, width=82))
            choice = input("Choose (1-3): ").strip() or "1"
            if choice == "2":
                out = Path("naza_orbit_sim_current.csv"); orbit_sim.export_csv(out, count=121, step_seconds=60)
                print(f"Saved {out}"); input("Enter...")
            elif choice == "3": return
    return orbit_simulation_flow


def _menu_factory(core, orbit_flow):
    def main_menu_loop(state: Dict) -> None:
        options = ["Model Manager","Chat with model","Road Scanner","Food/Water Scanner","Orbit Conditioning Simulation",
                   "View chat history","SpookyCombiner-1 Research Lab","Enable SpookyNaza tri-hybrid","Encryption status","Rekey / Rotate key","Exit"]
        while True:
            core.drain_stdin(); core.clear_screen(); core.header(state); print()
            print(core.boxed("Main Menu", [f"{i+1}) {opt}" for i,opt in enumerate(options)]))
            idx = core.read_menu_choice(len(options)); choice = options[idx]
            try:
                if choice == "Model Manager": core.model_manager(state)
                elif choice == "Chat with model": asyncio.run(core.chat_session(state))
                elif choice == "Road Scanner": asyncio.run(core.road_scanner_flow(state,"road"))
                elif choice == "Food/Water Scanner": asyncio.run(core.road_scanner_flow(state,"food"))
                elif choice == "Orbit Conditioning Simulation": orbit_flow()
                elif choice == "View chat history": asyncio.run(core.db_viewer_flow(state))
                elif choice == "SpookyCombiner-1 Research Lab": core.spooky_lab_flow(state)
                elif choice == "Enable SpookyNaza tri-hybrid": core.trihybrid_flow(state)
                elif choice == "Encryption status": core.encryption_status_flow(state)
                elif choice == "Rekey / Rotate key": core.rekey_flow(state)
                elif choice == "Exit": print("Goodbye."); return
            except KeyboardInterrupt: print("\nBack to menu.")
            except Exception as exc: print(f"That step stopped ({exc}). Back to menu."); input("Enter to continue...")
            core.drain_stdin()
    return main_menu_loop


def install(core) -> None:
    global _INSTALLED
    if _INSTALLED: return
    build_prompt = _build_prompt_factory(core); orbit_flow = _orbit_flow_factory(core)
    core.build_road_scanner_prompt = build_prompt; core.orbit_simulation_flow = orbit_flow
    core.main_menu_loop = _menu_factory(core, orbit_flow)
    def standalone_oqs_installer(dest=None):
        path = Path(dest) if dest else Path("install_liboqs_0.14.0.sh")
        if not path.exists(): raise FileNotFoundError("standalone minimal liboqs installer is missing")
        return path
    core.write_oqs_install_script = standalone_oqs_installer
    _INSTALLED = True
