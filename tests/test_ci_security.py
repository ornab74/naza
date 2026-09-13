import re
import unittest
from pathlib import Path

WORKFLOW = Path(__file__).parents[1] / ".github" / "workflows" / "lock-requirements.yml"

class CiSupplyChainTests(unittest.TestCase):
    def test_liboqs_archive_is_verified_before_extraction(self):
        workflow = WORKFLOW.read_text(encoding="utf-8")
        expected = re.search(r'LIBOQS_EXPECTED_SHA256="([0-9a-f]{64})"', workflow)
        self.assertIsNotNone(expected)
        verify_at = workflow.index('sha256sum -c -')
        extract_at = workflow.index('tar -xzf /tmp/liboqs.tar.gz')
        configure_at = workflow.index('cmake -S /tmp/liboqs-src')
        self.assertLess(verify_at, extract_at)
        self.assertLess(verify_at, configure_at)

    def test_workflow_change_triggers_lock_job(self):
        workflow = WORKFLOW.read_text(encoding="utf-8")
        self.assertIn("- .github/workflows/lock-requirements.yml", workflow)

    def test_lock_artifacts_receive_independent_provenance(self):
        workflow = WORKFLOW.read_text(encoding="utf-8")
        self.assertIn("id-token: write", workflow)
        self.assertIn("attestations: write", workflow)
        attest_at = workflow.index("uses: actions/attest@e59cbc1ad1ac2d59339667419eb8cdde6eb61e3d")
        sign_at = workflow.index("python /tmp/pq_sign_lock.py")
        upload_at = workflow.index("uses: actions/upload-artifact@ea165f8d65b6e75b540449e92b4886f43607fa02")
        self.assertLess(sign_at, attest_at)
        self.assertLess(attest_at, upload_at)
        for artifact in ("requirements.txt", "lock.manifest.json", "lock.manifest.pqsig", "pq_pubkey.b64"):
            self.assertIn(artifact, workflow[attest_at:upload_at])

    def test_ci_bootstrap_and_actions_are_immutable(self):
        workflow = WORKFLOW.read_text(encoding="utf-8")
        self.assertIn("python:3.12-slim@sha256:", workflow)
        self.assertIn("pip install --require-hashes -r bootstrap-requirements.txt", workflow)
        self.assertNotIn("pip install --upgrade pip", workflow)
        self.assertNotRegex(workflow, r"uses:\s+[^\s]+@v\d+(?:\s|$)")

if __name__ == "__main__":
    unittest.main()
