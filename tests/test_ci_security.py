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


if __name__ == "__main__":
    unittest.main()
