"""Runtime resource path helpers.

All bundled customer assets are resolved from the same root in source and in a
PyInstaller bundle.  Callers should resolve a profile asset through these
helpers instead of reconstructing repository-relative paths themselves.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path


def resource_root() -> Path:
    """Return the root containing packaged resources."""
    override = os.environ.get("RO_WORKBENCH_RESOURCE_ROOT")
    if override:
        return Path(override)
    meipass = getattr(sys, "_MEIPASS", None)
    if getattr(sys, "frozen", False) and isinstance(meipass, str):
        return Path(meipass)
    return Path(__file__).resolve().parents[4]


def profile_root(profile_id: str, *, root: Path | None = None) -> Path:
    """Return the asset root for one customer profile.

    ``root`` is injectable for tests and embedders.  The normal source and
    PyInstaller paths are both ``<resource_root>/customer_profiles/<id>``.
    """

    normalized_id = profile_id.strip()
    if (
        not normalized_id
        or normalized_id in {".", ".."}
        or "/" in normalized_id
        or "\\" in normalized_id
    ):
        raise ValueError(f"非法 Profile ID：{profile_id!r}")
    return (root or resource_root()) / "customer_profiles" / normalized_id


def find_profile_root(path: str | Path) -> Path | None:
    """Find the nearest profile directory containing ``profile.yaml``.

    Mapping files are allowed to use paths relative to their Profile root.
    This marker-based lookup also works when the same Profile tree is bundled
    by PyInstaller or copied to a temporary workspace.
    """

    candidate = Path(path).resolve()
    if candidate.is_file():
        candidate = candidate.parent
    for parent in (candidate, *candidate.parents):
        if (parent / "profile.yaml").is_file():
            return parent
    return None
