# PyInstaller spec for RO Workbench launcher
# Build: pyinstaller ro-workbench.spec

import sys
from pathlib import Path

# SPECPATH is the directory containing this spec file
ROOT = Path(SPECPATH).parent.parent
DATAS = []
for source, target in [
    (ROOT / "frontend" / "dist", "frontend/dist"),
    (ROOT / "templates", "templates"),
]:
    if source.exists():
        DATAS.append((str(source), target))

a = Analysis(
    [str(ROOT / "packages/ro_workbench_launcher/src/ro_workbench_launcher/launcher.py")],
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
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=None,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=None)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name="RO Workbench",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False if sys.platform == "darwin" else True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=None,
)

if sys.platform == "darwin":
    app = BUNDLE(
        exe,
        name="RO Workbench.app",
        icon=None,
        bundle_identifier="com.roworkbench.app",
        info_plist={
            "CFBundleShortVersionString": "0.1.0",
            "CFBundleName": "RO Workbench",
            "LSBackgroundOnly": "0",
            "LSUIElement": "1",
        },
    )
