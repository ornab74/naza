"""Fail-closed runtime check for the pinned production cryptographic backend."""
import hmac
import os

import oqs

import spooky_combiner as combiner
import spooky_trihybrid as tri


def main():
    version = oqs.oqs_version()
    if version != "0.14.0":
        raise SystemExit("ERROR: expected liboqs 0.14.0, found " + str(version))
    status = combiner.status(oqs)
    if not status.ready:
        raise SystemExit("ERROR: required liboqs KEMs unavailable: " + ", ".join(status.missing))

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
        return
    raise SystemExit("ERROR: tri-hybrid runtime accepted a tampered envelope")


if __name__ == "__main__":
    main()
