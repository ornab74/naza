"""Quantum-inspired 30-circuit router for Naza.

The router uses lightweight local retrieval (hashed token vectors), historical Clef
feedback, novelty, and entropy quality to sample one of 30 PennyLane circuit
profiles.  Only the selected circuit is executed, keeping the per-prompt cost
bounded even though the ensemble contains 30 hypotheses.
"""
from __future__ import annotations

import hashlib
import json
import math
import re
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

import numpy as np

try:
    import pennylane as qml
except Exception:  # pragma: no cover - exercised by runtime fallback
    qml = None


STATE_PATH = Path("clef_quantum_history.json")
DEFAULT_TEMPERATURE = 0.55
HISTORY_ALPHA = 0.20
MAX_ATTEMPTS = 500
RECENT_WINDOW = 20
EMBED_DIM = 256


@dataclass(frozen=True)
class CircuitProfile:
    id: str
    qubits: int
    topology: str
    bias: str


CIRCUITS: Tuple[CircuitProfile, ...] = (
    CircuitProfile("C01", 8, "GHZ -> ring-CP -> RX/RY remix", "emotional"),
    CircuitProfile("C02", 9, "butterfly CNOT -> RZ interference", "composition"),
    CircuitProfile("C03", 10, "prime-jump CP graph", "novelty"),
    CircuitProfile("C04", 11, "star entanglement -> phase echo", "focal subject"),
    CircuitProfile("C05", 12, "dual-ring CNOT/CP", "beauty"),
    CircuitProfile("C06", 13, "sparse hypergraph ZZZ", "complex semantics"),
    CircuitProfile("C07", 14, "QFT-lite -> inverse interference", "unusual concepts"),
    CircuitProfile("C08", 9, "brickwork CZ -> RY cascade", "realism"),
    CircuitProfile("C09", 10, "Fibonacci-distance CNOT", "organic structure"),
    CircuitProfile("C10", 11, "small-world CP network", "broad associations"),
    CircuitProfile("C11", 12, "hierarchical binary tree", "visual hierarchy"),
    CircuitProfile("C12", 13, "mirrored-half entanglement", "symmetry"),
    CircuitProfile("C13", 14, "alternating local/global ZZ", "epic scale"),
    CircuitProfile("C14", 8, "parity echo -> Hadamard remix", "stereotypes"),
    CircuitProfile("C15", 9, "XY-chain approximation", "motion"),
    CircuitProfile("C16", 10, "Ising-web phase circuit", "atmosphere"),
    CircuitProfile("C17", 11, "controlled-RY fanout", "character design"),
    CircuitProfile("C18", 12, "Moebius ring coupling", "surreal imagery"),
    CircuitProfile("C19", 13, "random-regular graph", "exploration"),
    CircuitProfile("C20", 14, "dense-low-depth CP", "maximal interaction"),
    CircuitProfile("C21", 8, "amplitude ladder", "minimalism"),
    CircuitProfile("C22", 9, "golden-angle RZ phases", "color harmony"),
    CircuitProfile("C23", 10, "SWAP network + CZ", "spatial relationships"),
    CircuitProfile("C24", 11, "global parity kick", "high drama"),
    CircuitProfile("C25", 12, "three-body phase lattice", "layered detail"),
    CircuitProfile("C26", 13, "butterfly + prime-jumps", "cinematic imagery"),
    CircuitProfile("C27", 14, "GHZ backbone + sparse ZZ", "awe"),
    CircuitProfile("C28", 10, "two-cluster bridge circuit", "contrast"),
    CircuitProfile("C29", 12, "recursive interferometer", "abstraction"),
    CircuitProfile("C30", 14, "reservoir-style phase cascade", "wildcard search"),
)

_PROFILE_INDEX = {p.id: i for i, p in enumerate(CIRCUITS)}

CATEGORY_HINTS: Dict[str, str] = {
    "realism": "realistic photo physical material lighting camera ordinary plausible",
    "stereotype": "stereotype archetype nerd culture character identity recognizable tropes",
    "stereotypes": "stereotype archetype nerd culture character identity recognizable tropes",
    "beauty": "beautiful aesthetic elegant color harmony pleasing polished",
    "emotion": "emotion expressive feeling mood human affect empathy",
    "emotional": "emotion expressive feeling mood human affect empathy",
    "epic": "epic cinematic vast monumental scale awe dramatic",
    "awe": "awe epic vast monumental sublime cinematic scale",
    "creative": "creative unusual novel exploratory surprising imaginative",
    "composition": "composition framing layout balance foreground background visual hierarchy",
    "character": "character face clothing pose personality design subject",
    "abstract": "abstract conceptual symbolic geometry surreal nonliteral",
    "road-risk": "road driving traffic weather obstacle visibility realistic safety environment",
    "chat": "language reasoning associations semantics question answer context",
}

CATEGORY_CIRCUIT_PRIORS: Dict[str, Dict[str, float]] = {
    "stereotype": {"C14": 1.00, "C17": 0.88, "C04": 0.82, "C28": 0.76, "C01": 0.70},
    "stereotypes": {"C14": 1.00, "C17": 0.88, "C04": 0.82, "C28": 0.76, "C01": 0.70},
    "realism": {"C08": 1.00, "C04": 0.84, "C23": 0.78, "C11": 0.72, "C28": 0.68},
    "road-risk": {"C08": 1.00, "C23": 0.88, "C11": 0.80, "C10": 0.74, "C04": 0.70},
    "beauty": {"C05": 1.00, "C22": 0.88, "C12": 0.78, "C11": 0.72, "C01": 0.68},
    "emotion": {"C01": 1.00, "C17": 0.82, "C16": 0.76, "C04": 0.72, "C05": 0.66},
    "emotional": {"C01": 1.00, "C17": 0.82, "C16": 0.76, "C04": 0.72, "C05": 0.66},
    "epic": {"C13": 1.00, "C27": 0.96, "C26": 0.84, "C24": 0.76, "C20": 0.70},
    "awe": {"C27": 1.00, "C13": 0.94, "C26": 0.82, "C24": 0.76, "C20": 0.70},
    "creative": {"C07": 0.94, "C19": 0.90, "C30": 0.88, "C18": 0.82, "C29": 0.78},
    "character": {"C17": 1.00, "C04": 0.88, "C01": 0.76, "C12": 0.68, "C28": 0.64},
    "composition": {"C02": 1.00, "C11": 0.90, "C23": 0.82, "C28": 0.74, "C05": 0.68},
    "abstract": {"C29": 1.00, "C18": 0.92, "C07": 0.86, "C03": 0.78, "C30": 0.74},
}


def _tokens(text: str) -> List[str]:
    return re.findall(r"[a-z0-9]+", (text or "").lower())


def _hashed_embedding(text: str, dim: int = EMBED_DIM) -> np.ndarray:
    """Dependency-free semantic-ish vector using signed feature hashing."""
    v = np.zeros(dim, dtype=float)
    toks = _tokens(text)
    if not toks:
        return v
    for tok in toks:
        digest = hashlib.blake2b(tok.encode("utf-8"), digest_size=8).digest()
        h = int.from_bytes(digest, "little")
        idx = h % dim
        sign = 1.0 if ((h >> 8) & 1) == 0 else -1.0
        v[idx] += sign
    norm = float(np.linalg.norm(v))
    return v / norm if norm > 0 else v


def _cosine(a: np.ndarray, b: np.ndarray) -> float:
    na = float(np.linalg.norm(a))
    nb = float(np.linalg.norm(b))
    if na == 0.0 or nb == 0.0:
        return 0.0
    # Map signed cosine into [0, 1] so it is compatible with the routing score.
    return max(0.0, min(1.0, (float(np.dot(a, b)) / (na * nb) + 1.0) / 2.0))


def _profile_text(profile: CircuitProfile) -> str:
    return f"{profile.bias} {profile.topology} {CATEGORY_HINTS.get(profile.bias, '')}"


_PROFILE_VECTORS = tuple(_hashed_embedding(_profile_text(p)) for p in CIRCUITS)


def entropy_band(category: Optional[str]) -> Tuple[float, float]:
    c = (category or "").strip().lower()
    if any(k in c for k in ("realism", "stereotype", "road", "photo")):
        return (0.72, 0.82)
    if any(k in c for k in ("beauty", "emotion", "emotional")):
        return (0.78, 0.88)
    if any(k in c for k in ("epic", "awe", "creative", "cinematic")):
        return (0.84, 0.92)
    return (0.78, 0.88)


def _entropy_quality(value: float, band: Tuple[float, float]) -> float:
    lo, hi = band
    value = max(0.0, min(1.0, float(value)))
    if lo <= value <= hi:
        return 1.0
    distance = lo - value if value < lo else value - hi
    # A miss of 0.20 or more receives no entropy-quality reward.
    return max(0.0, 1.0 - distance / 0.20)


def _default_state() -> dict:
    return {
        "version": 1,
        "circuits": {
            p.id: {
                "historical_score": 0.50,
                "mean_entropy": (sum(entropy_band(p.bias)) / 2.0),
                "runs": 0,
                "clef_updates": 0,
            }
            for p in CIRCUITS
        },
        "recent": [],
        "attempts": [],
    }


def load_state(path: Path = STATE_PATH) -> dict:
    if not path.exists():
        return _default_state()
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return _default_state()
    base = _default_state()
    if isinstance(raw, dict):
        for cid, item in raw.get("circuits", {}).items():
            if cid in base["circuits"] and isinstance(item, dict):
                base["circuits"][cid].update(item)
        if isinstance(raw.get("recent"), list):
            base["recent"] = [x for x in raw["recent"] if x in _PROFILE_INDEX][-RECENT_WINDOW:]
        if isinstance(raw.get("attempts"), list):
            base["attempts"] = raw["attempts"][-MAX_ATTEMPTS:]
    return base


def save_state(state: dict, path: Path = STATE_PATH) -> None:
    path.write_text(json.dumps(state, indent=2, sort_keys=True), encoding="utf-8")


def _novelty_scores(state: dict) -> np.ndarray:
    recent = state.get("recent", [])[-RECENT_WINDOW:]
    if not recent:
        return np.ones(len(CIRCUITS), dtype=float)
    counts = {cid: recent.count(cid) for cid in _PROFILE_INDEX}
    max_count = max(counts.values()) or 1
    return np.asarray([1.0 - counts[p.id] / max_count for p in CIRCUITS], dtype=float)


def _attempt_vector(attempt: dict) -> np.ndarray:
    stored = attempt.get("embedding")
    if isinstance(stored, list) and len(stored) == EMBED_DIM:
        try:
            v = np.asarray(stored, dtype=float)
            norm = float(np.linalg.norm(v))
            return v / norm if norm > 0 else v
        except Exception:
            pass
    # Backward-compatible migration path for early state files.
    feature_text = " ".join(str(x) for x in attempt.get("features", []))
    return _hashed_embedding(
        f"{attempt.get('question', '')} {attempt.get('category', '')} {feature_text}"
    )


def _relevance_and_history(
    question: str,
    category: str,
    state: dict,
) -> Tuple[np.ndarray, np.ndarray]:
    category_hint = CATEGORY_HINTS.get(category.lower(), "")
    query = _hashed_embedding(f"{question} {category} {category_hint}")
    base_rel = np.asarray([_cosine(query, v) for v in _PROFILE_VECTORS], dtype=float)
    priors = CATEGORY_CIRCUIT_PRIORS.get(category.lower(), {})
    if priors:
        prior_vec = np.asarray([float(priors.get(p.id, 0.0)) for p in CIRCUITS], dtype=float)
        base_rel = np.clip(0.62 * base_rel + 0.38 * prior_vec, 0.0, 1.0)

    # Retrieve high-scoring prior attempts. Their hashed semantic features become
    # local RAG evidence for whichever circuit produced them.
    attempts = [a for a in state.get("attempts", []) if a.get("clef_score") is not None]
    retrieved: List[Tuple[float, dict]] = []
    for a in attempts:
        sim = _cosine(query, _attempt_vector(a))
        retrieved.append((sim, a))
    retrieved.sort(key=lambda x: (x[0], float(x[1].get("clef_score", 0.0))), reverse=True)
    retrieved = retrieved[:12]

    rag = base_rel.copy()
    hist = np.asarray(
        [float(state["circuits"][p.id].get("historical_score", 0.5)) for p in CIRCUITS],
        dtype=float,
    )

    if retrieved:
        per_circuit: Dict[str, List[Tuple[float, float]]] = {}
        for sim, attempt in retrieved:
            cid = attempt.get("circuit_id")
            if cid in _PROFILE_INDEX:
                reward = max(0.0, min(1.0, float(attempt.get("clef_score", 0.0)) / 100.0))
                per_circuit.setdefault(cid, []).append((sim, reward))
        for cid, pairs in per_circuit.items():
            idx = _PROFILE_INDEX[cid]
            # Blend profile relevance with nearest successful prior-attempt evidence.
            evidence = max(sim * reward for sim, reward in pairs)
            rag[idx] = max(rag[idx], evidence)
            weight_sum = sum(max(1e-6, sim) for sim, _ in pairs)
            local_hist = sum(max(1e-6, sim) * reward for sim, reward in pairs) / weight_sum
            hist[idx] = 0.55 * hist[idx] + 0.45 * local_hist

    return np.clip(rag, 0.0, 1.0), np.clip(hist, 0.0, 1.0)


def softmax(values: Sequence[float], temperature: float = DEFAULT_TEMPERATURE) -> np.ndarray:
    t = max(1e-6, float(temperature))
    x = np.asarray(values, dtype=float) / t
    x -= np.max(x)
    ex = np.exp(x)
    total = float(np.sum(ex))
    return ex / total if total > 0 else np.full_like(ex, 1.0 / len(ex))


def _seed_from_text(text: str) -> int:
    return int.from_bytes(hashlib.blake2b(text.encode("utf-8"), digest_size=8).digest(), "little")


def _angle(seed: int, k: int, scale: float = 1.0) -> float:
    # Stable, non-random angle in [0.18*pi, 0.82*pi], then scaled.
    h = hashlib.blake2b(f"{seed}:{k}".encode(), digest_size=8).digest()
    u = int.from_bytes(h, "little") / float(2**64 - 1)
    return (0.18 + 0.64 * u) * math.pi * scale


def _mixing_scale(target_mid: float) -> float:
    # Higher target entropy -> rotations closer to pi/2. The range deliberately
    # avoids an exactly flat computational-basis distribution.
    return 0.72 + 0.42 * max(0.0, min(1.0, target_mid))


def _prepare_base(n: int, seed: int, target_mid: float) -> None:
    scale = _mixing_scale(target_mid)
    for w in range(n):
        qml.RY(_angle(seed, w, scale), wires=w)
        if w % 2:
            qml.RX(_angle(seed, 100 + w, 0.35), wires=w)


def _ring_cp(n: int, seed: int, offset: int = 0) -> None:
    for i in range(n):
        qml.ControlledPhaseShift(_angle(seed, 200 + offset + i, 0.55), wires=[i, (i + 1) % n])


def _prime_jumps(n: int, seed: int, offset: int = 0) -> None:
    for jump in (2, 3, 5):
        if jump >= n:
            continue
        for i in range(0, n, 2):
            j = (i + jump) % n
            if i != j:
                qml.ControlledPhaseShift(_angle(seed, 300 + offset + jump * 31 + i, 0.45), wires=[i, j])


def _butterfly(n: int) -> None:
    step = 1
    while step < n:
        for i in range(0, n, 2 * step):
            for j in range(i, min(i + step, n)):
                k = j + step
                if k < n:
                    qml.CNOT(wires=[j, k])
        step *= 2


def _apply_topology(index: int, n: int, seed: int, target_mid: float) -> None:
    """Apply the requested topology after a shared non-flat state preparation."""
    _prepare_base(n, seed, target_mid)

    if index == 1:  # GHZ -> ring-CP -> remix
        qml.Hadamard(wires=0)
        for i in range(1, n): qml.CNOT(wires=[0, i])
        _ring_cp(n, seed)
        for i in range(n): qml.RY(_angle(seed, 500 + i, 0.25), wires=i)
    elif index == 2:
        _butterfly(n)
        for i in range(n): qml.RZ(_angle(seed, 520 + i, 0.5), wires=i)
        for i in range(n): qml.Hadamard(wires=i)
    elif index == 3:
        _prime_jumps(n, seed)
        for i in range(0, n, 2): qml.RX(_angle(seed, 540 + i, 0.22), wires=i)
    elif index == 4:
        for i in range(1, n): qml.CNOT(wires=[0, i])
        for i in range(1, n): qml.RZ(_angle(seed, 560 + i, 0.45), wires=i)
        for i in reversed(range(1, n)): qml.CNOT(wires=[0, i])
        qml.RY(_angle(seed, 579, 0.35), wires=0)
    elif index == 5:
        for i in range(n): qml.CNOT(wires=[i, (i + 1) % n])
        for i in range(n): qml.ControlledPhaseShift(_angle(seed, 580 + i, 0.35), wires=[i, (i + 2) % n])
    elif index == 6:
        for i in range(0, n - 2, 3): qml.MultiRZ(_angle(seed, 600 + i, 0.35), wires=[i, i + 1, i + 2])
        _ring_cp(n, seed, 30)
    elif index == 7:
        for i in range(n): qml.Hadamard(wires=i)
        for i in range(n):
            for j in range(i + 1, min(n, i + 4)):
                qml.ControlledPhaseShift(math.pi / (2 ** (j - i)), wires=[j, i])
        for i in reversed(range(n)): qml.Hadamard(wires=i)
    elif index == 8:
        for layer in range(2):
            for i in range(layer, n - 1, 2): qml.CZ(wires=[i, i + 1])
            for i in range(n): qml.RY(_angle(seed, 620 + layer * n + i, 0.28), wires=i)
    elif index == 9:
        for jump in (1, 2, 3, 5):
            for i in range(n - jump):
                if i % 2 == 0: qml.CNOT(wires=[i, i + jump])
    elif index == 10:
        _ring_cp(n, seed, 60)
        _prime_jumps(n, seed, 60)
    elif index == 11:
        width = 1
        while width < n:
            for i in range(0, n - width, width * 2): qml.CNOT(wires=[i, i + width])
            width *= 2
    elif index == 12:
        for i in range(n // 2):
            qml.CNOT(wires=[i, n - 1 - i])
            qml.RY(_angle(seed, 660 + i, 0.3), wires=n - 1 - i)
    elif index == 13:
        for i in range(n - 1): qml.IsingZZ(_angle(seed, 680 + i, 0.25), wires=[i, i + 1])
        for i in range(n // 2): qml.IsingZZ(_angle(seed, 700 + i, 0.22), wires=[i, n - 1 - i])
        for i in range(0, n, 2): qml.RY(_angle(seed, 720 + i, 0.20), wires=i)
    elif index == 14:
        for i in range(1, n): qml.CNOT(wires=[0, i])
        for i in reversed(range(1, n)): qml.CNOT(wires=[0, i])
        for i in range(n): qml.Hadamard(wires=i)
        for i in range(0, n, 2): qml.RY(_angle(seed, 740 + i, 0.32), wires=i)
    elif index == 15:
        for i in range(n - 1):
            theta = _angle(seed, 760 + i, 0.22)
            qml.IsingXX(theta, wires=[i, i + 1]); qml.IsingYY(theta, wires=[i, i + 1])
    elif index == 16:
        for i in range(n - 1): qml.IsingZZ(_angle(seed, 780 + i, 0.34), wires=[i, i + 1])
        for i in range(n): qml.Hadamard(wires=i)
        _ring_cp(n, seed, 90)
    elif index == 17:
        for i in range(1, n): qml.CRY(_angle(seed, 800 + i, 0.42), wires=[0, i])
    elif index == 18:
        for i in range(n):
            j = (i + 1) % n
            qml.CNOT(wires=[i, j])
            if i % 2 == 0: qml.RZ(_angle(seed, 820 + i, 0.42), wires=j)
        qml.CNOT(wires=[0, n // 2])
    elif index == 19:
        # Deterministic pseudo-random regular-ish graph from the prompt seed.
        for i in range(n):
            for jump in (2, 5):
                j = (i + jump + (seed % 3)) % n
                if i < j: qml.CZ(wires=[i, j])
        for i in range(0, n, 3): qml.RY(_angle(seed, 840 + i, 0.30), wires=i)
    elif index == 20:
        for i in range(n):
            for jump in (1, 2, 3):
                j = (i + jump) % n
                if i < j: qml.ControlledPhaseShift(_angle(seed, 860 + i * 5 + jump, 0.24), wires=[i, j])
        for i in range(n): qml.RX(_angle(seed, 900 + i, 0.16), wires=i)
    elif index == 21:
        for i in range(n): qml.RY((i + 1) / n * math.pi * 0.42, wires=i)
        for i in range(n - 1): qml.CNOT(wires=[i, i + 1])
    elif index == 22:
        golden = math.pi * (3.0 - math.sqrt(5.0))
        for i in range(n):
            qml.RZ((i + 1) * golden, wires=i)
            qml.RY(_angle(seed, 920 + i, 0.22), wires=i)
        _ring_cp(n, seed, 110)
    elif index == 23:
        for layer in range(2):
            for i in range(layer, n - 1, 2):
                qml.SWAP(wires=[i, i + 1]); qml.CZ(wires=[i, i + 1])
        for i in range(n): qml.RY(_angle(seed, 940 + i, 0.22), wires=i)
    elif index == 24:
        for i in range(1, n): qml.CNOT(wires=[i, 0])
        qml.RZ(_angle(seed, 960, 0.75), wires=0)
        for i in reversed(range(1, n)): qml.CNOT(wires=[i, 0])
        for i in range(n): qml.RX(_angle(seed, 970 + i, 0.18), wires=i)
    elif index == 25:
        for i in range(0, n - 2, 2): qml.MultiRZ(_angle(seed, 990 + i, 0.30), wires=[i, i + 1, i + 2])
        for i in range(n): qml.RY(_angle(seed, 1010 + i, 0.20), wires=i)
    elif index == 26:
        _butterfly(n); _prime_jumps(n, seed, 130)
        for i in range(n): qml.RY(_angle(seed, 1030 + i, 0.18), wires=i)
    elif index == 27:
        qml.Hadamard(wires=0)
        for i in range(1, n): qml.CNOT(wires=[0, i])
        for i in range(0, n - 2, 3): qml.IsingZZ(_angle(seed, 1050 + i, 0.25), wires=[i, i + 2])
        for i in range(n): qml.RY(_angle(seed, 1070 + i, 0.16), wires=i)
    elif index == 28:
        mid = n // 2
        for start, end in ((0, mid), (mid, n)):
            for i in range(start, end - 1): qml.CNOT(wires=[i, i + 1])
        qml.CZ(wires=[mid - 1, mid])
        qml.RY(_angle(seed, 1090, 0.45), wires=mid)
    elif index == 29:
        span = 1
        while span < n:
            for i in range(0, n - span, 2 * span):
                qml.Hadamard(wires=i); qml.CZ(wires=[i, i + span])
            span *= 2
        for i in range(n): qml.RY(_angle(seed, 1110 + i, 0.20), wires=i)
    elif index == 30:
        for layer in range(3):
            _ring_cp(n, seed, 160 + layer * n)
            for i in range(n):
                qml.RZ(_angle(seed, 1140 + layer * n + i, 0.38), wires=i)
                qml.RY(_angle(seed, 1200 + layer * n + i, 0.14), wires=i)


def execute_circuit(profile: CircuitProfile, question: str, category: str) -> Tuple[float, str]:
    """Return normalized computational-basis entropy and backend label.

    If PennyLane is unavailable, a deterministic bounded proxy is returned.  The
    proxy stays inside the task's useful entropy neighborhood rather than
    pretending that maximum entropy is always desirable.
    """
    band = entropy_band(category or profile.bias)
    target_mid = sum(band) / 2.0
    seed = _seed_from_text(f"{profile.id}|{category}|{question}")

    if qml is None:
        # Deterministic +/- 0.045 around the target midpoint.
        jitter = ((seed % 10001) / 10000.0 - 0.5) * 0.09
        return max(0.0, min(1.0, target_mid + jitter)), "classical-proxy"

    try:
        dev = qml.device("default.qubit", wires=profile.qubits, shots=None)

        @qml.qnode(dev)
        def circuit():
            _apply_topology(_PROFILE_INDEX[profile.id] + 1, profile.qubits, seed, target_mid)
            return qml.probs(wires=range(profile.qubits))

        probs = np.asarray(circuit(), dtype=float)
        probs = probs[probs > 1e-15]
        entropy = -float(np.sum(probs * np.log2(probs)))
        normalized = entropy / float(profile.qubits)
        return max(0.0, min(1.0, normalized)), "pennylane"
    except Exception:
        jitter = ((seed % 10001) / 10000.0 - 0.5) * 0.09
        return max(0.0, min(1.0, target_mid + jitter)), "classical-proxy"


def _features(question: str, category: str, profile: CircuitProfile, entropy: float) -> List[str]:
    # Deliberately avoid persisting raw prompt tokens. The embedding stored beside
    # these coarse features is enough for nearest-attempt retrieval.
    return [category, profile.bias, f"entropy:{entropy:.3f}", f"tokens:{len(_tokens(question))}"]


def choose_circuit(
    question: str,
    category: str = "chat",
    *,
    temperature: float = DEFAULT_TEMPERATURE,
    top_k: int = 5,
    rng: Optional[np.random.Generator] = None,
    state_path: Path = STATE_PATH,
) -> dict:
    """Retrieve the closest profiles, sample within them, execute one, and persist the attempt."""
    state = load_state(state_path)
    rag, historical = _relevance_and_history(question, category, state)
    novelty = _novelty_scores(state)
    band = entropy_band(category)
    entropy_quality = np.asarray(
        [
            _entropy_quality(float(state["circuits"][p.id].get("mean_entropy", sum(band) / 2.0)), band)
            for p in CIRCUITS
        ],
        dtype=float,
    )

    scores = 0.45 * rag + 0.30 * historical + 0.15 * novelty + 0.10 * entropy_quality

    # RAG retrieves the closest profiles first; collapse occurs only inside that
    # candidate set. This preserves meaningful probabilities at T=0.55 instead
    # of diluting every prompt across all 30 circuits.
    k = max(1, min(len(CIRCUITS), int(top_k)))
    shortlist = np.argsort(rag)[::-1][:k]
    shortlist_p = softmax(scores[shortlist], temperature=temperature)
    probabilities = np.zeros(len(CIRCUITS), dtype=float)
    probabilities[shortlist] = shortlist_p
    rng = rng or np.random.default_rng()
    selected_idx = int(rng.choice(shortlist, p=shortlist_p))
    profile = CIRCUITS[selected_idx]
    measured_entropy, backend = execute_circuit(profile, question, category)

    stats = state["circuits"][profile.id]
    runs = int(stats.get("runs", 0))
    prior_entropy = float(stats.get("mean_entropy", measured_entropy))
    stats["runs"] = runs + 1
    stats["mean_entropy"] = (prior_entropy * runs + measured_entropy) / (runs + 1)
    state["recent"] = (state.get("recent", []) + [profile.id])[-RECENT_WINDOW:]

    attempt_id = hashlib.blake2b(
        f"{time.time_ns()}|{profile.id}|{question}".encode("utf-8"), digest_size=8
    ).hexdigest()
    semantic_vector = _hashed_embedding(f"{question} {category} {CATEGORY_HINTS.get(category.lower(), '')}")
    attempt = {
        "id": attempt_id,
        "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
        "question_hash": hashlib.sha256(question.encode("utf-8")).hexdigest(),
        "embedding": [round(float(x), 7) for x in semantic_vector],
        "category": category,
        "circuit_id": profile.id,
        "clef_score": None,
        "entropy": measured_entropy,
        "features": _features(question, category, profile, measured_entropy),
    }
    state["attempts"] = (state.get("attempts", []) + [attempt])[-MAX_ATTEMPTS:]
    save_state(state, state_path)

    ranking = shortlist[np.argsort(shortlist_p)[::-1]]
    return {
        "attempt_id": attempt_id,
        "circuit": asdict(profile),
        "entropy": measured_entropy,
        "entropy_band": band,
        "entropy_quality": _entropy_quality(measured_entropy, band),
        "backend": backend,
        "score": float(scores[selected_idx]),
        "probability": float(probabilities[selected_idx]),
        "top_candidates": [
            {
                "id": CIRCUITS[int(i)].id,
                "probability": float(probabilities[int(i)]),
                "score": float(scores[int(i)]),
            }
            for i in ranking
        ],
    }


def record_clef_result(
    score: float,
    *,
    attempt_id: Optional[str] = None,
    state_path: Path = STATE_PATH,
) -> dict:
    """Attach a real Clef result to an attempt and update historical reward."""
    score = float(score)
    if not math.isfinite(score) or not (0.0 <= score <= 100.0):
        raise ValueError("Clef score must be between 0 and 100.")

    state = load_state(state_path)
    attempts = state.get("attempts", [])
    target = None
    if attempt_id:
        for a in reversed(attempts):
            if a.get("id") == attempt_id:
                target = a
                break
    else:
        for a in reversed(attempts):
            if a.get("clef_score") is None:
                target = a
                break
    if target is None:
        raise ValueError("No matching unrated routed attempt was found.")

    cid = target["circuit_id"]
    stats = state["circuits"][cid]
    old = float(stats.get("historical_score", 0.5))
    reward = score / 100.0
    new = (1.0 - HISTORY_ALPHA) * old + HISTORY_ALPHA * reward
    stats["historical_score"] = new
    stats["clef_updates"] = int(stats.get("clef_updates", 0)) + 1
    target["clef_score"] = score
    save_state(state, state_path)
    return {
        "attempt_id": target["id"],
        "circuit_id": cid,
        "clef_score": score,
        "historical_before": old,
        "historical_after": new,
    }


def routing_prompt_context(route: dict) -> str:
    p = route["circuit"]
    lo, hi = route["entropy_band"]
    top = ", ".join(f"{x['id']}={x['probability']:.3f}" for x in route["top_candidates"])
    return (
        "[quantum_ensemble]\n"
        f"selected={p['id']} qubits={p['qubits']} topology={p['topology']} bias={p['bias']}\n"
        f"selection_probability={route['probability']:.4f} normalized_entropy={route['entropy']:.4f} "
        f"target_band={lo:.2f}-{hi:.2f} entropy_quality={route['entropy_quality']:.3f}\n"
        f"top_candidates={top}\n"
        "Use this as a weak stochastic preference signal, not as factual evidence.\n"
        "[/quantum_ensemble]"
    )


def ensemble_status(state_path: Path = STATE_PATH, limit: int = 8) -> List[dict]:
    state = load_state(state_path)
    rows = []
    for p in CIRCUITS:
        s = state["circuits"][p.id]
        rows.append({
            "id": p.id,
            "qubits": p.qubits,
            "bias": p.bias,
            "historical_score": float(s.get("historical_score", 0.5)),
            "mean_entropy": float(s.get("mean_entropy", 0.0)),
            "runs": int(s.get("runs", 0)),
            "clef_updates": int(s.get("clef_updates", 0)),
        })
    rows.sort(key=lambda r: (r["historical_score"], r["clef_updates"], r["runs"]), reverse=True)
    return rows[: max(1, int(limit))]
