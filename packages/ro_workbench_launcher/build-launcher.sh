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

if [[ ! -d "$ROOT/frontend/dist" ]]; then
    echo "frontend/dist 不存在，请先在 frontend/ 下执行 pnpm run build" >&2
    exit 1
fi

uv run pyinstaller "$ROOT/packages/ro_workbench_launcher/ro-workbench.spec" --noconfirm

# PyInstaller outputs to dist/ in cwd; move to package dir
mv "$ROOT/dist/RO Workbench" "$DIST/" 2>/dev/null || true
mv "$ROOT/dist/RO Workbench.app" "$DIST/" 2>/dev/null || true

echo "==> Done: $DIST/"
ls -lh "$DIST/"
