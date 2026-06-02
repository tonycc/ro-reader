#!/bin/bash
# Build RO Workbench launcher as single-file executable.
# Usage: bash packages/ro_workbench_launcher/build-launcher.sh [platform]
#
# Requires: uv, PyInstaller

set -euo pipefail
PLATFORM="${1:-$(uname -s)}"
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
DIST="$ROOT/packages/ro_workbench_launcher/dist"
mkdir -p "$DIST"

echo "==> Installing build deps..."
cd "$ROOT"
uv sync --group build-launcher 2>/dev/null || uv pip install pyinstaller

echo "==> Building launcher for $PLATFORM..."

# The launcher imports ro_workbench_launcher which depends on ro_workbench_api,
# so we need to ensure all workspace packages are importable.
PYTHONPATH="$ROOT/packages/ro_generator/src:$ROOT/packages/ro_workbench_api/src:$ROOT/packages/ro_workbench_launcher/src"
export PYTHONPATH

pyinstaller \
    --onefile \
    --name "RO Workbench" \
    --add-data "$ROOT/packages/ro_workbench_launcher/src/ro_workbench_launcher/_placeholder_server.py:ro_workbench_launcher" \
    --hidden-import ro_workbench_launcher \
    --hidden-import ro_generator \
    $([[ "$PLATFORM" == "Darwin" ]] && echo "--windowed") \
    "$ROOT/packages/ro_workbench_launcher/src/ro_workbench_launcher/launcher.py"

# PyInstaller outputs to dist/ in cwd; move to package dir
mv "$ROOT/dist/RO Workbench" "$DIST/" 2>/dev/null || true
mv "$ROOT/dist/RO Workbench.app" "$DIST/" 2>/dev/null || true

echo "==> Done: $DIST/"
ls -lh "$DIST/"
