"""Verify that release-facing metadata uses the launcher release version."""

from __future__ import annotations

import json
import re
import sys
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def text(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def first(pattern: str, content: str, *, label: str) -> str:
    match = re.search(pattern, content)
    if match is None:
        raise ValueError(f"无法读取 {label}")
    return match.group(1)


def package_version(path: str) -> str:
    with (ROOT / path).open("rb") as stream:
        payload = tomllib.load(stream)
    return str(payload["project"]["version"])


def main() -> int:
    workflow = text(".github/workflows/build-launcher.yml")
    expected = first(r'APP_VERSION:\s*"([^"]+)"', workflow, label="APP_VERSION")

    checks: dict[str, str] = {
        "root pyproject": package_version("pyproject.toml"),
        "ro-generator pyproject": package_version("packages/ro_generator/pyproject.toml"),
        "workbench-api pyproject": package_version("packages/ro_workbench_api/pyproject.toml"),
        "launcher pyproject": package_version("packages/ro_workbench_launcher/pyproject.toml"),
        "frontend package": str(json.loads(text("frontend/package.json"))["version"]),
        "ro-generator __version__": first(
            r'__version__\s*=\s*"([^"]+)"',
            text("packages/ro_generator/src/ro_generator/__init__.py"),
            label="ro-generator __version__",
        ),
        "workbench-api __version__": first(
            r'__version__\s*=\s*"([^"]+)"',
            text("packages/ro_workbench_api/src/ro_workbench_api/__init__.py"),
            label="workbench-api __version__",
        ),
        "launcher __version__": first(
            r'__version__\s*=\s*"([^"]+)"',
            text("packages/ro_workbench_launcher/src/ro_workbench_launcher/__init__.py"),
            label="launcher __version__",
        ),
        "FastAPI metadata": first(
            r'FastAPI\(title="RO Workbench API", version="([^"]+)"',
            text("packages/ro_workbench_api/src/ro_workbench_api/app.py"),
            label="FastAPI metadata",
        ),
        "installer": first(
            r'#define MyAppVersion "([^"]+)"',
            text("packages/ro_workbench_launcher/installer.iss"),
            label="installer version",
        ),
        "macOS bundle": first(
            r'CFBundleShortVersionString": "([^"]+)"',
            text("packages/ro_workbench_launcher/ro-workbench.spec"),
            label="macOS bundle version",
        ),
    }

    ui_versions = re.findall(
        r"<code>v([^<]+)</code>", text("frontend/src/components/layout/TopBar.vue")
    )
    if not ui_versions:
        raise ValueError("无法读取前端设置页版本")
    checks.update(
        {f"frontend settings row {index}": value for index, value in enumerate(ui_versions, 1)}
    )

    lock = text("uv.lock")
    for package in (
        "ro-generator",
        "ro-reader-workspace",
        "ro-workbench-api",
        "ro-workbench-launcher",
    ):
        checks[f"uv.lock {package}"] = first(
            rf'name = "{re.escape(package)}"\nversion = "([^"]+)"',
            lock,
            label=f"uv.lock {package}",
        )

    mismatches = {label: value for label, value in checks.items() if value != expected}
    if mismatches:
        details = ", ".join(f"{label}={value!r}" for label, value in mismatches.items())
        print(f"release metadata mismatch: expected {expected!r}; {details}", file=sys.stderr)
        return 1

    print(f"release metadata ok: {expected}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
