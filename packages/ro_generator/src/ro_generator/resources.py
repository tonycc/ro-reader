"""Runtime resource path helpers."""

from __future__ import annotations

import os
import sys
from pathlib import Path


def resource_root() -> Path:
    """Return the root containing packaged resources such as templates."""
    override = os.environ.get("RO_WORKBENCH_RESOURCE_ROOT")
    if override:
        return Path(override)
    meipass = getattr(sys, "_MEIPASS", None)
    if getattr(sys, "frozen", False) and isinstance(meipass, str):
        return Path(meipass)
    return Path(__file__).resolve().parents[4]
