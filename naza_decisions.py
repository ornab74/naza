#!/usr/bin/env python3
"""OpenAI Decisions API adapter for Naza road-risk classification."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from typing import Any, Dict, Iterable, Mapping, Optional

from openai import OpenAI

MODEL = "gpt-6-luna"

RISK_CHOICES = [
    {"value": "Low", "description": "Normal driving conditions with no material hazard. Visibility, surface, traffic, and obstacles do not require meaningful extra caution."},
    {"value": "Medium", "description": "A meaningful hazard or degraded condition is present, but a careful driver can usually proceed using ordinary precautions such as reduced speed or increased following distance."},
    {"value": "High", "description": "Substantial immediate driving risk from severe visibility loss, flooding, ice, major obstruction, dangerous traffic behavior, or multiple compounding hazards. Delay, reroute, or stop if safe."},
]


@dataclass(frozen=True)
class RoadRiskDecision:
    label: str
    confidence: float
    probabilities: Dict[str, float]
    review_required: bool
    model: str = MODEL

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


def _scene_text(scene: Mapping[str, Any], entropy_score: Optional[float] = None) -> str:
    fields = {
        "location": scene.get("location", "unspecified location"),
        "road_type": scene.get("road_type", "unknown"),
        "weather": scene.get("weather", "unknown"),
        "traffic": scene.get("traffic", "unknown"),
        "obstacles": scene.get("obstacles", "none"),
        "sensor_notes": scene.get("sensor_notes", "none"),
    }
    lines = ["Classify the road risk for this driving scene."]
    lines.extend(f"{key}: {value}" for key, value in fields.items())
    if entropy_score is not None:
        lines.append(
            "system_entropy_signal: "
            f"{max(0.0, min(1.0, float(entropy_score))):.3f} "
            "(weak confidence-only auxiliary signal; never override observed road hazards)"
        )
    return "\n".join(lines)


def _probability_map(items: Iterable[Any]) -> Dict[str, float]:
    out: Dict[str, float] = {}
    for item in items or []:
        label = getattr(item, "value", None)
        if label is None and isinstance(item, Mapping):
            label = item.get("value") or item.get("label")
        probability = getattr(item, "probability", None)
        if probability is None and isinstance(item, Mapping):
            probability = item.get("probability")
        if label is not None and probability is not None:
            out[str(label)] = float(probability)
    return out


def decide_road_risk(
    scene: Mapping[str, Any],
    *,
    entropy_score: Optional[float] = None,
    min_confidence: float = 0.65,
    client: Optional[OpenAI] = None,
) -> RoadRiskDecision:
    """Return Low/Medium/High plus confidence and probability distribution.

    Low-confidence decisions are marked review_required so callers can collect
    better sensor data or fall back to the local Naza classifier.
    """
    client = client or OpenAI()
    decision = client.decisions.create(
        model=MODEL,
        input=_scene_text(scene, entropy_score),
        questions=[
            {
                "type": "choice",
                "name": "road_risk",
                "instructions": (
                    "Choose the single overall road-risk level. Base the decision on observable "
                    "surface condition, visibility, weather, traffic, obstacles, and sensor notes. "
                    "Treat missing or vague data as uncertainty rather than inventing hazards. "
                    "When multiple real hazards compound, prefer the more conservative level."
                ),
                "choices": RISK_CHOICES,
            }
        ],
    )

    if not getattr(decision, "answers", None):
        raise RuntimeError("Decisions API returned no answers")

    answer = decision.answers[0]
    if getattr(answer, "type", None) == "refusal":
        raise RuntimeError(f"Decision refused for {getattr(answer, 'name', 'road_risk')}")
    if getattr(answer, "type", None) != "choice":
        raise RuntimeError(f"Unexpected decision answer type: {getattr(answer, 'type', None)!r}")

    label = str(answer.choice)
    if label not in {"Low", "Medium", "High"}:
        raise RuntimeError(f"Unexpected road-risk choice: {label!r}")

    confidence = float(getattr(answer, "confidence", 0.0))
    probabilities = _probability_map(getattr(answer, "probabilities", []))
    return RoadRiskDecision(
        label=label,
        confidence=confidence,
        probabilities=probabilities,
        review_required=confidence < float(min_confidence),
    )


def main() -> int:
    scene = {
        "location": input("Location: ").strip() or "unspecified location",
        "road_type": input("Road type: ").strip() or "unknown",
        "weather": input("Weather/visibility: ").strip() or "unknown",
        "traffic": input("Traffic: ").strip() or "unknown",
        "obstacles": input("Obstacles: ").strip() or "none",
        "sensor_notes": input("Sensor notes: ").strip() or "none",
    }
    result = decide_road_risk(scene)
    print(json.dumps(result.to_dict(), indent=2))
    return 2 if result.review_required else 0


if __name__ == "__main__":
    raise SystemExit(main())
