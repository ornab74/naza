#!/usr/bin/env python3
"""Naza native Termux entrypoint.

The stable application core lives in ``naza_core.py``. Runtime-only hardening
and the deterministic orbit-conditioning simulation are installed by
``naza_orbit_patch`` before control is handed to the core.
"""
from __future__ import annotations

import naza_core as core
from naza_orbit_patch import install as install_orbit_patch


def main() -> None:
    install_orbit_patch(core)
    core.main()


if __name__ == "__main__":
    main()
