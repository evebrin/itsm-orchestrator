"""The one place that puts the pinned vendor checkouts on sys.path (ADR 0003).

The change repository is installed editable from its submodule, so it needs no entry here.
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
VENDOR = ROOT / "vendor"
PATHS = [VENDOR / "itscm-451z-agent" / "src", VENDOR / "pm-agent"]


def activate():
    for p in PATHS:
        if str(p) not in sys.path:
            sys.path.append(str(p))
