"""Fail-closed native Termux runtime preflight for Naza."""
from __future__ import annotations

import ctypes
import hmac
import importlib.metadata as md
import os
from pathlib import Path


def require_version(dist: str, expected: str) -> None:
    got = md.version(dist)
    if got != expected:
        raise SystemExit(f"ERROR: expected {dist} {expected}, found {got}")


def main() -> None:
    require_version("llama-cpp-python", "0.3.1")
    require_version("cryptography", "46.0.5")
    llama_dir = os.environ.get("LLAMA_CPP_LIB_PATH", "")
    if not llama_dir:
        raise SystemExit("ERROR: LLAMA_CPP_LIB_PATH is not set")
    libdir = Path(llama_dir)
    candidates = list(libdir.glob("libllama.so*"))
    if not candidates:
        raise SystemExit(f"ERROR: libllama.so not found under {libdir}")
    try:
        ctypes.CDLL(str(candidates[0]), mode=getattr(ctypes, "RTLD_GLOBAL", 0))
    except OSError as exc:
        raise SystemExit(f"ERROR: libllama loader failure: {exc}") from exc
    import llama_cpp
    from llama_cpp import Llama
    if not callable(Llama):
        raise SystemExit("ERROR: llama_cpp.Llama API unavailable")

    import oqs
    import spooky_combiner as combiner
    import spooky_trihybrid as tri
    import naza_orbit_sim as orbit_sim
    version = oqs.oqs_version()
    if version != "0.14.0":
        raise SystemExit("ERROR: expected liboqs 0.14.0, found " + str(version))
    status = combiner.status(oqs)
    if not status.ready:
        raise SystemExit("ERROR: required liboqs KEMs unavailable: " + ", ".join(status.missing))
    for name in ("ML-KEM-1024", "HQC-256"):
        with oqs.KeyEncapsulation(name) as kem:
            public_key = kem.generate_keypair()
            ciphertext, sender_secret = kem.encap_secret(public_key)
            receiver_secret = kem.decap_secret(ciphertext)
            if not hmac.compare_digest(sender_secret, receiver_secret):
                raise SystemExit("ERROR: " + name + " round-trip failed")

    payload = os.urandom(32); protector = os.urandom(32); context = b"naza/runtime-preflight/v2"
    envelope = tri.create_envelope(payload, protector, oqs, context)
    recovered = tri.open_envelope(envelope, protector, oqs, context)
    if not hmac.compare_digest(payload, recovered):
        raise SystemExit("ERROR: tri-hybrid runtime self-test failed")
    tampered = bytearray(envelope); tampered[-1] ^= 1
    try:
        tri.open_envelope(bytes(tampered), protector, oqs, context)
    except combiner.SpookyCombinerError:
        pass
    else:
        raise SystemExit("ERROR: tri-hybrid runtime accepted a tampered envelope")

    orbit_errors = orbit_sim.verify_source()
    if orbit_errors.get("latitude_deg", 1.0) > 1e-5 or orbit_errors.get("longitude_deg", 1.0) > 1e-5:
        raise SystemExit("ERROR: orbit simulator no longer matches supplied calibration CSV")
    if orbit_errors.get("altitude_km", 1.0) > 1e-3:
        raise SystemExit("ERROR: orbit altitude calibration mismatch")
    current_orbit = orbit_sim.propagate()
    for field in ("latitude_deg", "longitude_deg", "altitude_km", "orbital_phase_0_1"):
        if field not in current_orbit:
            raise SystemExit("ERROR: orbit simulator missing field " + field)
    print("native runtime preflight: PASS")
    print("  llama-cpp-python 0.3.1 native library: PASS")
    print("  liboqs ML-KEM-1024/HQC-256 round trips: PASS")
    print("  SpookyNaza tri-hybrid/tamper rejection: PASS")
    print("  orbital simulation calibration/current propagation: PASS")


if __name__ == "__main__":
    main()
