"""Read and synchronize the release version from the repository VERSION file."""

from __future__ import annotations

import argparse
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
VERSION_PATH = ROOT / "VERSION"
VERSION_PATTERN = re.compile(r"\d+\.\d+\.\d+(?:[-+][0-9A-Za-z.-]+)?")


def read_version() -> str:
    version = VERSION_PATH.read_text(encoding="utf-8").strip()
    if not VERSION_PATTERN.fullmatch(version):
        raise ValueError(f"VERSION 必须是语义版本号（例如 1.2.3），当前为：{version!r}")
    return version


def _replace_once(path: Path, pattern: str, replacement: str, *, label: str) -> None:
    content = path.read_text(encoding="utf-8")
    updated, count = re.subn(pattern, replacement, content, count=1, flags=re.MULTILINE)
    if count != 1:
        raise ValueError(f"无法在 {label} 中定位唯一版本字段：{path}")
    if updated != content:
        path.write_text(updated, encoding="utf-8")


def synchronize(version: str) -> None:
    for relative_path in (
        "pyproject.toml",
        "packages/ro_generator/pyproject.toml",
        "packages/ro_workbench_api/pyproject.toml",
        "packages/ro_workbench_launcher/pyproject.toml",
    ):
        _replace_once(
            ROOT / relative_path,
            r'^version = "[^"]+"$',
            f'version = "{version}"',
            label="Python package metadata",
        )

    _replace_once(
        ROOT / "frontend/package.json",
        r'^  "version": "[^"]+",$',
        f'  "version": "{version}",',
        label="frontend package metadata",
    )

    for relative_path in (
        "packages/ro_generator/src/ro_generator/__init__.py",
        "packages/ro_workbench_api/src/ro_workbench_api/__init__.py",
        "packages/ro_workbench_launcher/src/ro_workbench_launcher/__init__.py",
    ):
        _replace_once(
            ROOT / relative_path,
            r'^__version__ = "[^"]+"$',
            f'__version__ = "{version}"',
            label="Python runtime version",
        )

    _replace_once(
        ROOT / "packages/ro_workbench_launcher/installer.iss",
        r'^#define MyAppVersion "[^"]+"$',
        f'#define MyAppVersion "{version}"',
        label="Windows installer metadata",
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "command",
        nargs="?",
        choices=("print", "sync"),
        default="print",
        help="print the version or synchronize generated release metadata",
    )
    args = parser.parse_args()

    version = read_version()
    if args.command == "sync":
        synchronize(version)
        print(f"release metadata synchronized: {version}")
    else:
        print(version)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
