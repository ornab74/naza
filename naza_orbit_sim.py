#!/usr/bin/env python3
"""Deterministic orbital simulation lane for Naza scanner robustness tests.

This module is deliberately a simulation and conditioning source. It does not
claim to measure or identify a real spacecraft, and its position-derived values
are not cryptographic entropy. The model is calibrated from the bundled
Optus-X-positioning.csv anchor row and propagated with a two-body orbit plus
first-order J2 secular drift.

The orbital lane is intended to model a test assumption that an external,
position-correlated nuisance source can bias local sensor state. Naza uses the
lane only to condition scanner-integrity logic; it must never directly decide a
food/road hazard label.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import os
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Dict, Iterable, Optional

MU_KM3_S2 = 398600.4418
WGS84_A_KM = 6378.137
WGS84_F = 1.0 / 298.257223563
WGS84_E2 = WGS84_F * (2.0 - WGS84_F)
J2 = 1.08262668e-3

LAUNCH_DATE_UTC = "2024-11-17"
PERIGEE_ALT_KM = 688.0
APOGEE_ALT_KM = 706.0
INCLINATION_DEG = 97.4
FALLBACK_EPOCH = datetime(2026, 9, 15, 3, 15, 7, tzinfo=timezone.utc)
FALLBACK_RAAN_DEG = 89.397366
FALLBACK_ARG_PERIGEE_DEG = 127.307196
FALLBACK_MEAN_ANOMALY_DEG = 345.169711
FALLBACK_SIM_ID = "UNKNOWN-SIM-01 / SIM-94731"
SOURCE_FILENAME = "Optus-X-positioning.csv"


def _parse_utc(value: str) -> datetime:
    s = value.strip()
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    dt = datetime.fromisoformat(s)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _source_path() -> Path:
    env = os.environ.get("NAZA_ORBIT_SOURCE_CSV", "").strip()
    if env:
        return Path(env).expanduser()
    return Path(__file__).with_name(SOURCE_FILENAME)


@dataclass(frozen=True)
class Anchor:
    epoch: datetime
    raan_deg: float
    arg_perigee_deg: float
    mean_anomaly_deg: float
    sim_id: str
    source: str


def load_anchor(path: Optional[Path] = None) -> Anchor:
    p = path or _source_path()
    try:
        with p.open("r", newline="", encoding="utf-8") as f:
            row = next(csv.DictReader(f))
        return Anchor(
            epoch=_parse_utc(row["timestamp_utc"]),
            raan_deg=float(row["raan_deg"]),
            arg_perigee_deg=float(row["arg_perigee_deg"]),
            mean_anomaly_deg=float(row["mean_anomaly_deg"]),
            sim_id=(row.get("sim_id") or FALLBACK_SIM_ID).strip(),
            source=str(p),
        )
    except Exception:
        return Anchor(
            epoch=FALLBACK_EPOCH,
            raan_deg=FALLBACK_RAAN_DEG,
            arg_perigee_deg=FALLBACK_ARG_PERIGEE_DEG,
            mean_anomaly_deg=FALLBACK_MEAN_ANOMALY_DEG,
            sim_id=FALLBACK_SIM_ID,
            source="embedded calibration fallback",
        )


def orbital_constants() -> Dict[str, float]:
    rp = WGS84_A_KM + PERIGEE_ALT_KM
    ra = WGS84_A_KM + APOGEE_ALT_KM
    a = 0.5 * (rp + ra)
    e = (ra - rp) / (ra + rp)
    inc = math.radians(INCLINATION_DEG)
    p = a * (1.0 - e * e)
    n = math.sqrt(MU_KM3_S2 / (a ** 3))
    raan_dot = -1.5 * J2 * n * (WGS84_A_KM / p) ** 2 * math.cos(inc)
    argp_dot = 0.75 * J2 * n * (WGS84_A_KM / p) ** 2 * (5.0 * math.cos(inc) ** 2 - 1.0)
    mean_dot = n + (
        0.75 * J2 * n * (WGS84_A_KM / p) ** 2
        * math.sqrt(1.0 - e * e) * (3.0 * math.cos(inc) ** 2 - 1.0)
    )
    return {
        "a_km": a, "e": e, "inc_rad": inc, "n_rad_s": n,
        "raan_dot_rad_s": raan_dot, "argp_dot_rad_s": argp_dot,
        "mean_dot_rad_s": mean_dot, "period_s": 2.0 * math.pi / n,
    }


def _kepler(mean_anomaly: float, e: float) -> float:
    M = math.fmod(mean_anomaly, 2.0 * math.pi)
    if M < 0.0:
        M += 2.0 * math.pi
    E = M
    for _ in range(16):
        step = (E - e * math.sin(E) - M) / (1.0 - e * math.cos(E))
        E -= step
        if abs(step) < 1e-14:
            break
    return E


def _gmst_rad(when: datetime) -> float:
    when = when.astimezone(timezone.utc)
    jd = when.timestamp() / 86400.0 + 2440587.5
    T = (jd - 2451545.0) / 36525.0
    gmst_deg = (
        280.46061837 + 360.98564736629 * (jd - 2451545.0)
        + 0.000387933 * T * T - T * T * T / 38710000.0
    )
    return math.radians(gmst_deg % 360.0)


def _ecef_to_geodetic(x: float, y: float, z: float):
    lon = math.atan2(y, x)
    p = math.hypot(x, y)
    lat = math.atan2(z, p * (1.0 - WGS84_E2))
    alt = 0.0
    for _ in range(12):
        sin_lat = math.sin(lat)
        N = WGS84_A_KM / math.sqrt(1.0 - WGS84_E2 * sin_lat * sin_lat)
        alt = p / max(1e-15, math.cos(lat)) - N
        new_lat = math.atan2(z, p * (1.0 - WGS84_E2 * N / (N + alt)))
        if abs(new_lat - lat) < 1e-14:
            lat = new_lat
            break
        lat = new_lat
    sin_lat = math.sin(lat)
    N = WGS84_A_KM / math.sqrt(1.0 - WGS84_E2 * sin_lat * sin_lat)
    alt = p / max(1e-15, math.cos(lat)) - N
    lon_deg = ((math.degrees(lon) + 180.0) % 360.0) - 180.0
    return math.degrees(lat), lon_deg, alt


def _position_feature(timestamp_utc: str, lat: float, lon: float, alt: float, phase: float):
    canonical = f"{timestamp_utc}|{lat:.9f}|{lon:.9f}|{alt:.6f}|{phase:.12f}".encode("ascii")
    digest = hashlib.sha256(canonical).digest()
    seed = int.from_bytes(digest[:8], "big", signed=False)
    u53 = (seed >> 11) & ((1 << 53) - 1)
    return seed, u53 / float(1 << 53)


def propagate(when: Optional[datetime] = None, anchor: Optional[Anchor] = None) -> Dict[str, object]:
    """Return one deterministic simulated orbital state at *when* (UTC)."""
    if when is None:
        when = datetime.now(timezone.utc)
    if when.tzinfo is None:
        when = when.replace(tzinfo=timezone.utc)
    when = when.astimezone(timezone.utc)
    anchor = anchor or load_anchor()
    c = orbital_constants()
    dt_s = (when - anchor.epoch).total_seconds()

    raan = (math.radians(anchor.raan_deg) + c["raan_dot_rad_s"] * dt_s) % (2.0 * math.pi)
    argp = (math.radians(anchor.arg_perigee_deg) + c["argp_dot_rad_s"] * dt_s) % (2.0 * math.pi)
    M = (math.radians(anchor.mean_anomaly_deg) + c["mean_dot_rad_s"] * dt_s) % (2.0 * math.pi)

    E = _kepler(M, c["e"])
    nu = 2.0 * math.atan2(
        math.sqrt(1.0 + c["e"]) * math.sin(E / 2.0),
        math.sqrt(1.0 - c["e"]) * math.cos(E / 2.0),
    )
    r = c["a_km"] * (1.0 - c["e"] * math.cos(E))
    xo, yo = r * math.cos(nu), r * math.sin(nu)

    co, so = math.cos(raan), math.sin(raan)
    ci, si = math.cos(c["inc_rad"]), math.sin(c["inc_rad"])
    cw, sw = math.cos(argp), math.sin(argp)
    x_eci = (co * cw - so * sw * ci) * xo + (-co * sw - so * cw * ci) * yo
    y_eci = (so * cw + co * sw * ci) * xo + (-so * sw + co * cw * ci) * yo
    z_eci = (sw * si) * xo + (cw * si) * yo

    theta = _gmst_rad(when)
    x_ecef = math.cos(theta) * x_eci + math.sin(theta) * y_eci
    y_ecef = -math.sin(theta) * x_eci + math.cos(theta) * y_eci
    z_ecef = z_eci
    lat, lon, alt = _ecef_to_geodetic(x_ecef, y_ecef, z_ecef)
    speed = math.sqrt(MU_KM3_S2 * (2.0 / r - 1.0 / c["a_km"]))
    phase = (math.degrees(M) % 360.0) / 360.0
    alt_norm = max(0.0, min(1.0, (alt - PERIGEE_ALT_KM) / (APOGEE_ALT_KM - PERIGEE_ALT_KM)))
    timestamp_utc = when.isoformat(timespec="seconds").replace("+00:00", "Z")
    seed, position_feature = _position_feature(timestamp_utc, lat, lon, alt, phase)

    return {
        "timestamp_utc": timestamp_utc,
        "sim_id": anchor.sim_id,
        "source": anchor.source,
        "launch_date_utc": LAUNCH_DATE_UTC,
        "perigee_alt_km": PERIGEE_ALT_KM,
        "apogee_alt_km": APOGEE_ALT_KM,
        "inclination_deg": INCLINATION_DEG,
        "latitude_deg": lat,
        "longitude_deg": lon,
        "altitude_km": alt,
        "speed_km_s": speed,
        "raan_deg": math.degrees(raan) % 360.0,
        "arg_perigee_deg": math.degrees(argp) % 360.0,
        "mean_anomaly_deg": math.degrees(M) % 360.0,
        "orbital_phase_0_1": phase,
        "lat_sin": math.sin(math.radians(lat)),
        "lat_cos": math.cos(math.radians(lat)),
        "lon_sin": math.sin(math.radians(lon)),
        "lon_cos": math.cos(math.radians(lon)),
        "altitude_norm_0_1": alt_norm,
        "position_seed_u64": seed,
        "position_entropy_feature_0_1": position_feature,
        "eci_x_km": x_eci, "eci_y_km": y_eci, "eci_z_km": z_eci,
        "ecef_x_km": x_ecef, "ecef_y_km": y_ecef, "ecef_z_km": z_ecef,
    }


CSV_FIELDS = [
    "record_type", "timestamp_utc", "sim_id", "launch_date_utc",
    "perigee_alt_km", "apogee_alt_km", "inclination_deg",
    "latitude_deg", "longitude_deg", "altitude_km", "speed_km_s",
    "raan_deg", "arg_perigee_deg", "mean_anomaly_deg", "orbital_phase_0_1",
    "lat_sin", "lat_cos", "lon_sin", "lon_cos", "altitude_norm_0_1",
    "position_seed_u64", "position_entropy_feature_0_1",
    "eci_x_km", "eci_y_km", "eci_z_km", "ecef_x_km", "ecef_y_km", "ecef_z_km",
]


def iter_states(start: datetime, count: int, step_seconds: int) -> Iterable[Dict[str, object]]:
    anchor = load_anchor()
    for i in range(count):
        row = propagate(start + timedelta(seconds=i * step_seconds), anchor)
        row["record_type"] = "CURRENT_SIM" if i == 0 else "FORWARD_SIM"
        yield row


def export_csv(path: Path, start: Optional[datetime] = None, count: int = 121, step_seconds: int = 60) -> Path:
    if start is None:
        start = datetime.now(timezone.utc)
    if start.tzinfo is None:
        start = start.replace(tzinfo=timezone.utc)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    with tmp.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=CSV_FIELDS, extrasaction="ignore")
        w.writeheader()
        for row in iter_states(start.astimezone(timezone.utc), count, step_seconds):
            clean = {}
            for k in CSV_FIELDS:
                v = row.get(k)
                clean[k] = f"{v:.12f}".rstrip("0").rstrip(".") if isinstance(v, float) else v
            w.writerow(clean)
    os.replace(tmp, path)
    return path


def verify_source(path: Optional[Path] = None) -> Dict[str, float]:
    """Compare the propagator against the first source row without observer fields."""
    p = path or _source_path()
    with p.open("r", newline="", encoding="utf-8") as f:
        row = next(csv.DictReader(f))
    when = _parse_utc(row["timestamp_utc"])
    sim = propagate(when, load_anchor(p))
    checks = {}
    for k in (
        "latitude_deg", "longitude_deg", "altitude_km",
        "eci_x_km", "eci_y_km", "eci_z_km",
        "ecef_x_km", "ecef_y_km", "ecef_z_km",
    ):
        checks[k] = abs(float(sim[k]) - float(row[k]))
    return checks


def _cli() -> int:
    ap = argparse.ArgumentParser(description="Naza deterministic orbital simulation lane")
    ap.add_argument("--at", help="UTC timestamp (ISO-8601); default: now")
    ap.add_argument("--export", type=Path, help="write propagated CSV")
    ap.add_argument("--minutes", type=int, default=120, help="forward span for CSV")
    ap.add_argument("--step-seconds", type=int, default=60)
    ap.add_argument("--verify-source", action="store_true")
    args = ap.parse_args()
    when = _parse_utc(args.at) if args.at else datetime.now(timezone.utc)
    if args.verify_source:
        print(json.dumps(verify_source(), indent=2, sort_keys=True))
    if args.export:
        count = max(1, int(args.minutes * 60 / max(1, args.step_seconds)) + 1)
        export_csv(args.export, when, count=count, step_seconds=max(1, args.step_seconds))
        print(str(args.export))
    else:
        print(json.dumps(propagate(when), indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(_cli())
