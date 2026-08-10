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


def release_version() -> str:
    version = text("VERSION").strip()
    if re.fullmatch(r"\d+\.\d+\.\d+(?:[-+][0-9A-Za-z.-]+)?", version) is None:
        raise ValueError(f"VERSION 不是有效的语义版本号：{version!r}")
    return version


def main() -> int:
    workflow = text(".github/workflows/build-launcher.yml")
    expected = release_version()
    if "python scripts/release_version.py sync" not in workflow:
        raise ValueError("CI 构建必须先同步 VERSION 派生元数据")

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
        "installer": first(
            r'#define MyAppVersion "([^"]+)"',
            text("packages/ro_workbench_launcher/installer.iss"),
            label="installer version",
        ),
    }

    api_source = text("packages/ro_workbench_api/src/ro_workbench_api/app.py")
    if "from ro_workbench_api import __version__" not in api_source:
        raise ValueError("FastAPI metadata 必须复用 ro_workbench_api.__version__")
    if 'FastAPI(title="RO Workbench API", version=__version__' not in api_source:
        raise ValueError("FastAPI metadata 未使用 ro_workbench_api.__version__")
    checks["FastAPI metadata"] = expected

    spec_source = text("packages/ro_workbench_launcher/ro-workbench.spec")
    if 'APP_VERSION = (ROOT / "VERSION")' not in spec_source:
        raise ValueError("PyInstaller spec 必须读取根目录 VERSION")
    if '"CFBundleShortVersionString": APP_VERSION' not in spec_source:
        raise ValueError("macOS bundle 未使用 VERSION")
    checks["macOS bundle"] = expected

    top_bar = text("frontend/src/components/layout/TopBar.vue")
    ui_version_marker = "<code>v{{ APP_VERSION }}</code>"
    if top_bar.count(ui_version_marker) != 3:
        raise ValueError("前端设置页必须使用构建注入的 APP_VERSION")
    checks["frontend settings"] = expected

    vite_config = text("frontend/vite.config.ts")
    if 'new URL("../VERSION", import.meta.url)' not in vite_config:
        raise ValueError("Vite 必须读取根目录 VERSION")
    if '"import.meta.env.VITE_APP_VERSION"' not in vite_config:
        raise ValueError("Vite 未注入 VITE_APP_VERSION")
    checks["frontend build injection"] = expected

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
