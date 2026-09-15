from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]


class OrbitConditioningRegressionTests(unittest.TestCase):
    def text(self, name):
        return (ROOT / name).read_text(encoding="utf-8")

    def test_entrypoint_is_modular(self):
        s = self.text("main.py")
        self.assertIn("import naza_core as core", s)
        self.assertIn("install_orbit_patch(core)", s)

    def test_position_lane_is_bounded_and_confidence_only(self):
        s = self.text("naza_orbit_patch.py")
        self.assertIn("max(-0.08, min(0.08", s)
        self.assertIn("Never raise or lower the risk label solely", s)
        self.assertIn("not cryptographic entropy", s)
        self.assertIn("Orbit Conditioning Simulation", s)

    def test_calibration_csv_has_no_observer_look_angles(self):
        header = self.text("Optus-X-positioning.csv").splitlines()[0].lower()
        for retired in ("azimuth", "elevation", "slant_range", "observer"):
            self.assertNotIn(retired, header)
        for required in ("timestamp_utc", "raan_deg", "arg_perigee_deg", "mean_anomaly_deg", "eci_x_km", "ecef_x_km"):
            self.assertIn(required, header)

    def test_liboqs_is_minimal_and_single_job(self):
        s = self.text("install_liboqs_0.14.0.sh")
        self.assertIn('OQS_MINIMAL_BUILD="KEM_ml_kem_1024;KEM_hqc_256"', s)
        self.assertIn("OQS_BUILD_ONLY_LIB=ON", s)
        self.assertIn("OQS_DIST_BUILD=OFF", s)
        self.assertIn("--parallel 1", s)
        self.assertNotIn("ML_DSA", s)

    def test_android_llama_loader_is_verified(self):
        s = self.text("install-native-termux-repair.sh")
        self.assertIn("--no-binary llama-cpp-python", s)
        self.assertIn("LLAMA_CPP_LIB_PATH", s)
        self.assertIn("libllama.so", s)
        self.assertIn('sys.platform.startswith("android")', s)
        self.assertIn("CMAKE_BUILD_PARALLEL_LEVEL=1", s)


if __name__ == "__main__":
    unittest.main()
