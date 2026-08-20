# PyInstaller spec for RO Workbench launcher
#
# Platform strategy:
#   macOS  : EXE (all-in) + BUNDLE → RO Workbench.app → DMG
#   Windows: EXE (stub) + COLLECT  → RO Workbench/ folder → ZIP
#
# Why different strategies:
#   - macOS BUNDLE requires an EXE directly; COLLECT+BUNDLE crashes in PyInstaller 6.x.
#   - Windows onedir avoids temp-dir extraction that triggers antivirus / Defender.

import sys
from pathlib import Path

ROOT = Path(SPECPATH).parent.parent
APP_VERSION = (ROOT / "VERSION").read_text(encoding="utf-8").strip()
DATAS = []
for source, target in [
    (ROOT / "frontend" / "dist", "frontend/dist"),
    (ROOT / "customer_profiles", "customer_profiles"),
    (ROOT / "packages" / "ro_workbench_launcher" / "resources", "resources"),
]:
    if source.exists():
        DATAS.append((str(source), target))

COMMON = dict(
    pathex=[
        str(ROOT / "packages/ro_generator/src"),
        str(ROOT / "packages/ro_workbench_api/src"),
        str(ROOT / "packages/ro_workbench_launcher/src"),
    ],
    binaries=[],
    datas=DATAS,
    hiddenimports=[
        "ro_generator",
        "ro_generator.models",
        "ro_generator.errors",
        "ro_generator.schema",
        "ro_generator.base_schema",
        "ro_generator.workbook_reader",
        "ro_generator.validator",
        "ro_generator.resolver",
        "ro_generator.resources",
        "ro_generator.profiles",
        "ro_generator.profiles.base",
        "ro_generator.profiles.registry",
        "ro_generator.profiles.ro",
        "ro_generator.document_model",
        "ro_generator.template_mapping",
        "ro_generator.renderer",
        "ro_generator.packager",
        "ro_generator.generator",
        "ro_generator.source_index",
        "ro_generator.workbench_service",
        "ro_generator.workbook_editor",
        "ro_generator.cli",
        "ro_workbench_api",
        "ro_workbench_api.app",
        "ro_workbench_launcher",
        "openpyxl",
        "yaml",
        "pypdf",
        "ro_generator.pdf_stamp",
        "uvicorn",
        "uvicorn.loops",
        "uvicorn.loops.auto",
        "uvicorn.protocols",
        "uvicorn.protocols.http",
        "uvicorn.protocols.http.auto",
        "fastapi",
        "starlette",
        "pydantic",
        "pystray",
        "PIL",
    ],
    hookspath=[],
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
)

a = Analysis(
    [str(ROOT / "packages/ro_workbench_launcher/src/ro_workbench_launcher/launcher.py")],
    **COMMON,
)

pyz = PYZ(a.pure, a.zipped_data)

APP_NAME = "赛肯单据生成工具"

if sys.platform == "darwin":
    # ── macOS ────────────────────────────────────────────────────────────────
    # BUNDLE requires an EXE (not COLLECT) in PyInstaller 6.x on macOS.
    exe = EXE(
        pyz, a.scripts, a.binaries, a.zipfiles, a.datas, [],
        name=APP_NAME,
        debug=False, strip=False, upx=True, upx_exclude=[],
        runtime_tmpdir=None, console=False,
        disable_windowed_traceback=False,
        argv_emulation=False, target_arch=None,
        codesign_identity=None, entitlements_file=None, icon=None,
    )
    app = BUNDLE(
        exe,
        name=f"{APP_NAME}.app",
        icon=None,
        bundle_identifier="com.saiken.doctools",
        info_plist={
            "CFBundleShortVersionString": APP_VERSION,
            "CFBundleName": APP_NAME,
            "LSBackgroundOnly": "0",
            "LSUIElement": "1",
        },
    )

else:
    # ── Windows (and Linux) ──────────────────────────────────────────────────
    # onedir: EXE stub + COLLECT → folder, no temp extraction, no AV trigger.
    exe = EXE(
        pyz, a.scripts, [],
        name=APP_NAME,
        debug=False, strip=False, upx=True, upx_exclude=[],
        runtime_tmpdir=None, console=False,
        disable_windowed_traceback=False,
        argv_emulation=False, target_arch=None,
        codesign_identity=None, entitlements_file=None, icon=None,
    )
    coll = COLLECT(
        exe, a.binaries, a.zipfiles, a.datas,
        strip=False, upx=True, upx_exclude=[],
        name=APP_NAME,
    )
