import tempfile
import unittest
from pathlib import Path

import numpy as np

import quantum_ensemble as qe


class QuantumEnsembleTests(unittest.TestCase):
    def test_all_circuits_stay_under_15_qubits(self):
        self.assertEqual(len(qe.CIRCUITS), 30)
        self.assertTrue(all(1 <= c.qubits < 15 for c in qe.CIRCUITS))

    def test_softmax_is_probability_distribution(self):
        p = qe.softmax([0.1, 0.2, 0.9], temperature=0.55)
        self.assertAlmostEqual(float(p.sum()), 1.0, places=10)
        self.assertGreater(p[2], p[1])

    def test_entropy_bands(self):
        self.assertEqual(qe.entropy_band("realism"), (0.72, 0.82))
        self.assertEqual(qe.entropy_band("beauty"), (0.78, 0.88))
        self.assertEqual(qe.entropy_band("epic"), (0.84, 0.92))

    def test_choose_and_feedback_update(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "state.json"
            route = qe.choose_circuit(
                "stereotypical Arch Linux nerd",
                "stereotype",
                rng=np.random.default_rng(7),
                state_path=path,
            )
            self.assertIn(route["circuit"]["id"], {c.id for c in qe.CIRCUITS})
            self.assertGreaterEqual(route["entropy"], 0.0)
            self.assertLessEqual(route["entropy"], 1.0)
            self.assertEqual(
                [x["id"] for x in route["top_candidates"]],
                ["C14", "C17", "C04", "C28", "C01"],
            )
            state = qe.load_state(path)
            self.assertNotIn("question", state["attempts"][-1])
            self.assertIn("embedding", state["attempts"][-1])
            update = qe.record_clef_result(94.3, attempt_id=route["attempt_id"], state_path=path)
            expected = 0.8 * 0.5 + 0.2 * 0.943
            self.assertAlmostEqual(update["historical_after"], expected, places=8)


if __name__ == "__main__":
    unittest.main()
