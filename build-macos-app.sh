#!/usr/bin/env bash

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PYTHON_BIN="${ROOT_DIR}/.venv/bin/python"

if [[ ! -x "${PYTHON_BIN}" ]]; then
    echo "Missing ${PYTHON_BIN}. Run 'uv sync --group dev' first."
    exit 1
fi

"${PYTHON_BIN}" -m PyInstaller \
    --noconfirm \
    --windowed \
    --name "spotDL Web Downloader" \
    --osx-bundle-identifier "com.spotdl.webdownloader" \
    --collect-data pykakasi \
    --add-data "${ROOT_DIR}/templates:templates" \
    --add-data "${ROOT_DIR}/static:static" \
    "${ROOT_DIR}/app.py"

echo
echo "Build complete:"
echo "  ${ROOT_DIR}/dist/spotDL Web Downloader.app"
