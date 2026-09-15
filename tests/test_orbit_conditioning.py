import csv
import sys
import unittest
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).parents[1]
sys.path.insert(0, str(ROOT))

import naza_orbit_sim as orbit

MAIN = (ROOT / "main.py").read_text(encoding="utf-8")
RUN = (ROOT / "run_naza.sh").read_text(encoding="utf-8")
PREFLIGHT = (ROOT / "naza_crypto_preflight.py").read_text(encoding="utf-8")
INSTALL = (ROOT / "install-native-termux-repair.sh").read_text(encoding="utf-8")
OQS_INSTALL = (ROOT / "install_liboqs_0.14.0.sh").read_text(encoding="utf-8")
SOURCE = ROOT / "Optus-X-positioning.csv"


class OrbitConditioningTests(unittest.TestCase):
    def test_source_anchor_reproduces_published_position(self):
        errors = orbit.verify_source(SOURCE)
        self.assertLess(errors["latitude_deg"], 1e-5)
        self.assertLess(errors["longitude_deg"], 1e-5)
        self.assertLess(errors["altitude_km"], 1e-3)
        for key in ("eci_x_km", "eci_y_km", "eci_z_km", "ecef_x_km", "ecef_y_km", "ecef_z_km"):
            self.assertLess(errors[key], 1e-3, key)

    def test_second_source_row_is_reproduced(self):
        with SOURCE.open(newline="", encoding="utf-8") as f:
            rows = list(csv.DictReader(f))
        row = rows[1]
        when = datetime.fromisoformat(row["timestamp_utc"].replace("Z", "+00:00")).astimezone(timezone.utc)
        sim = orbit.propagate(when, orbit.load_anchor(SOURCE))
        self.assertAlmostEqual(sim["latitude_deg"], float(row["latitude_deg"]), places=5)
        self.assertAlmostEqual(sim["longitude_deg"], float(row["longitude_deg"]), places=5)
        self.assertAlmostEqual(sim["altitude_km"], float(row["altitude_km"]), places=3)
        self.assertAlmostEqual(sim["raan_deg"], float(row["raan_deg"]), places=5)
        self.assertAlmostEqual(sim["arg_perigee_deg"], float(row["arg_perigee_deg"]), places=5)
        self.assertAlmostEqual(sim["mean_anomaly_deg"], float(row["mean_anomaly_deg"]), places=5)

    def test_prompt_has_separate_bounded_orbit_lane(self):
        self.assertIn("def orbit_position_quantum_state", MAIN)
        self.assertIn("nuisance = max(-0.08, min(0.08", MAIN)
        self.assertIn("Position quantum state:", MAIN)
        self.assertIn("not cryptographic entropy", MAIN)
        self.assertIn("Never raise or lower the risk label solely because of orbital", MAIN)
        self.assertIn("Timestamp and calibrate direct local sensors", MAIN)
        self.assertIn("Cross-check important scene facts", MAIN)
        self.assertIn("Maintain before/during/after baseline windows", MAIN)

    def test_orbit_surface_and_runtime_anchor_are_wired(self):
        self.assertIn("Orbit Conditioning Simulation", MAIN)
        self.assertIn("orbit_sim.export_csv", MAIN)
        self.assertIn("NAZA_ORBIT_SOURCE_CSV", RUN)
        self.assertIn("Optus-X-positioning.csv", RUN)
        self.assertIn("orbit_sim.verify_source", PREFLIGHT)
        self.assertIn("Optus-X-positioning.csv", INSTALL)

    def test_all_liboqs_build_paths_are_minimal_single_job(self):
        for text in (INSTALL, OQS_INSTALL, MAIN):
            self.assertIn('OQS_MINIMAL_BUILD="KEM_ml_kem_1024;KEM_hqc_256"', text)
            self.assertNotIn("OQS_ENABLE_SIG_ML_DSA=ON", text)
        self.assertIn("cmake --build build --parallel 1", INSTALL)
        self.assertIn("cmake --build build --parallel 1", OQS_INSTALL)
        self.assertIn("cmake --build build --parallel 1", MAIN)


if __name__ == "__main__":
    unittest.main()
