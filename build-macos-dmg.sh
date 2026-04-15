#!/usr/bin/env bash

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PYTHON_BIN="${ROOT_DIR}/.venv/bin/python"

if [[ ! -x "${PYTHON_BIN}" ]]; then
    echo "Missing ${PYTHON_BIN}. Run './setup --group dev' first."
    exit 1
fi

eval "$(
    "${PYTHON_BIN}" - <<'PY'
import shlex
from project_meta import APP_NAME, APP_VERSION

payload = {
    "APP_NAME": APP_NAME,
    "APP_VERSION": APP_VERSION,
}
for key, value in payload.items():
    print(f"{key}={shlex.quote(str(value))}")
PY
)"

APP_BUNDLE="${ROOT_DIR}/dist/${APP_NAME}.app"
DEFAULT_OUTPUT="${HOME}/Downloads/${APP_NAME} ${APP_VERSION}.dmg"
OUTPUT_PATH="${1:-${DEFAULT_OUTPUT}}"

if [[ ! -d "${APP_BUNDLE}" ]]; then
    echo "Missing ${APP_BUNDLE}. Run './build-macos-app.sh' first."
    exit 1
fi

STAGING_DIR="$(mktemp -d /tmp/spotdl-cask-dmg.XXXXXX)"
cleanup() {
    rm -rf "${STAGING_DIR}"
}
trap cleanup EXIT

mkdir -p "${STAGING_DIR}"
ditto "${APP_BUNDLE}" "${STAGING_DIR}/${APP_NAME}.app"
ln -s /Applications "${STAGING_DIR}/Applications"

mkdir -p "$(dirname "${OUTPUT_PATH}")"
rm -f "${OUTPUT_PATH}"

hdiutil create \
    -volname "${APP_NAME}" \
    -srcfolder "${STAGING_DIR}" \
    -format UDZO \
    -ov \
    "${OUTPUT_PATH}"

if [[ -n "${MACOS_CODESIGN_IDENTITY:-}" ]]; then
    echo "Signing DMG with identity: ${MACOS_CODESIGN_IDENTITY}"
    codesign --force --sign "${MACOS_CODESIGN_IDENTITY}" "${OUTPUT_PATH}"
fi

echo
echo "DMG complete:"
echo "  ${OUTPUT_PATH}"
