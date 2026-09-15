"""Fail-closed runtime check for Naza's pinned native Termux crypto + llama stack."""
import ctypes
import hmac
import os

import llama_cpp
import oqs

import spooky_combiner as combiner
import spooky_trihybrid as tri


def main():
    # Prove Android can resolve the exact package-local llama shared library graph
    # in the same environment used by run_naza.sh.
    llama_dir = os.environ.get("LLAMA_CPP_LIB_PATH", "")
    if not llama_dir:
        raise SystemExit("ERROR: LLAMA_CPP_LIB_PATH is not set")
    llama_so = os.path.join(llama_dir, "libllama.so")
    if not os.path.isfile(llama_so):
        raise SystemExit("ERROR: libllama.so missing: " + llama_so)
    ctypes.CDLL(llama_so)
    if getattr(llama_cpp, "__version__", None) != "0.3.1":
        raise SystemExit("ERROR: expected llama-cpp-python 0.3.1")
    llama_cpp.llama_backend_init()
    llama_cpp.llama_backend_free()

    version = oqs.oqs_version()
    if version != "0.14.0":
        raise SystemExit("ERROR: expected liboqs 0.14.0, found " + str(version))
    status = combiner.status(oqs)
    if not status.ready:
        raise SystemExit("ERROR: required liboqs KEMs unavailable: " + ", ".join(status.missing))

    # Real KEM round trips catch builds that advertise an algorithm but cannot use it.
    for name in ("ML-KEM-1024", "HQC-256"):
        with oqs.KeyEncapsulation(name) as kem:
            public = kem.generate_keypair()
            ciphertext, sender = kem.encap_secret(public)
            receiver = kem.decap_secret(ciphertext)
            if not hmac.compare_digest(sender, receiver):
                raise SystemExit("ERROR: KEM round trip failed: " + name)

    payload = os.urandom(32)
    protector = os.urandom(32)
    context = b"naza/runtime-preflight/v1"
    envelope = tri.create_envelope(payload, protector, oqs, context)
    recovered = tri.open_envelope(envelope, protector, oqs, context)
    if not hmac.compare_digest(payload, recovered):
        raise SystemExit("ERROR: tri-hybrid runtime self-test failed")

    tampered = bytearray(envelope)
    tampered[-1] ^= 1
    try:
        tri.open_envelope(bytes(tampered), protector, oqs, context)
    except combiner.SpookyCombinerError:
        print("Naza native runtime preflight: PASS")
        return
    raise SystemExit("ERROR: tri-hybrid runtime accepted a tampered envelope")


if __name__ == "__main__":
    main()
