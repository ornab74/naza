import re
import unittest
from pathlib import Path

ROOT = Path(__file__).parents[1]
INSTALLER = ROOT / "install-native-termux-repair.sh"
OQS_INSTALLER = ROOT / "install_liboqs_0.14.0.sh"
RUNNER = ROOT / "run_naza.sh"
UNLOCK = ROOT / "naza_unlock.sh"
MAIN = ROOT / "main.py"
REQ = ROOT / "requirements.in"


class NativeTermuxSecurityTests(unittest.TestCase):
    def test_removed_runtime_dependencies_stay_removed(self):
        req = REQ.read_text(encoding="utf-8").lower()
        self.assertNotRegex(req, r"^psutil(?:[<=> ]|$)", msg=req)
        self.assertNotRegex(req, r"^pennylane(?:[<=> ]|$)", msg=req)
        main = MAIN.read_text(encoding="utf-8").lower()
        self.assertNotIn("import psutil", main)
        self.assertNotIn("import pennylane", main)

    def test_runtime_has_no_retired_android_launch_api(self):
        retired_api = "termux-" + "fingerprint"
        guest_runtime = "pro" + "ot"
        for path in (RUNNER, UNLOCK):
            text = path.read_text(encoding="utf-8").lower()
            self.assertNotIn(retired_api, text, path)
            self.assertNotRegex(text, rf"(^|[^a-z0-9_]){guest_runtime}(-distro)?([^a-z0-9_]|$)", path)

    def test_gate3_is_hardware_backed_and_policy_checked(self):
        unlock = UNLOCK.read_text(encoding="utf-8")
        self.assertIn("inside_secure_hardware", unlock)
        self.assertIn("enforced_by_secure_hardware", unlock)
        self.assertIn("validity_duration_seconds", unlock)
        self.assertIn("SHA256withRSA", unlock)
        self.assertIn("secrets.token_hex(32)", unlock)

    def test_native_launcher_enforces_hardening(self):
        runner = RUNNER.read_text(encoding="utf-8")
        self.assertIn("NAZA_REQUIRE_PROCESS_HARDENING=1", runner)
        self.assertIn("naza_crypto_preflight.py", runner)
        self.assertIn("ulimit -c 0", runner)
        self.assertNotIn("libpython3.", runner)

    def test_liboqs_archive_is_verified_before_extraction(self):
        script = OQS_INSTALLER.read_text(encoding="utf-8")
        self.assertLess(script.index('verify_sha256 "$OQS_TARBALL"'), script.index('tar -xzf "$OQS_TARBALL"'))
        self.assertIn("-DOQS_ENABLE_KEM_ML_KEM=ON", script)
        self.assertIn("-DOQS_ENABLE_KEM_HQC=ON", script)

    def test_repair_installer_preserves_existing_data(self):
        installer = INSTALLER.read_text(encoding="utf-8")
        self.assertIn("not rekeyed or intentionally deleted", installer)
        for marker in (".enc_key", "encrypted history", "models"):
            self.assertIn(marker, installer)


if __name__ == "__main__":
    unittest.main()
