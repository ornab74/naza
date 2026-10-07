import unittest

from naza_decisions import decide_road_risk


class Probability:
    def __init__(self, value, probability):
        self.value = value
        self.probability = probability


class Answer:
    type = "choice"
    choice = "High"
    confidence = 0.82
    probabilities = [
        Probability("Low", 0.03),
        Probability("Medium", 0.15),
        Probability("High", 0.82),
    ]


class Decisions:
    def create(self, **kwargs):
        self.kwargs = kwargs
        return type("Decision", (), {"answers": [Answer()]})()


class FakeClient:
    def __init__(self):
        self.decisions = Decisions()


class DecisionsTests(unittest.TestCase):
    def test_returns_choice_confidence_and_probabilities(self):
        client = FakeClient()
        result = decide_road_risk(
            {
                "location": "I-95",
                "road_type": "highway",
                "weather": "dense fog",
                "traffic": "high",
                "obstacles": "stalled vehicle",
                "sensor_notes": "visibility 20m",
            },
            client=client,
        )
        self.assertEqual(result.label, "High")
        self.assertAlmostEqual(result.confidence, 0.82)
        self.assertEqual(result.probabilities["High"], 0.82)
        self.assertFalse(result.review_required)

    def test_low_confidence_routes_to_review(self):
        client = FakeClient()
        client.decisions.create = lambda **kwargs: type(
            "Decision",
            (),
            {
                "answers": [
                    type(
                        "A",
                        (),
                        {
                            "type": "choice",
                            "choice": "Medium",
                            "confidence": 0.44,
                            "probabilities": [],
                        },
                    )()
                ]
            },
        )()
        result = decide_road_risk({"weather": "unknown"}, client=client)
        self.assertTrue(result.review_required)


if __name__ == "__main__":
    unittest.main()
