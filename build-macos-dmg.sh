#!/usr/bin/env bash

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
APP_NAME="spotDL Web Downloader"
APP_BUNDLE="${ROOT_DIR}/dist/${APP_NAME}.app"
DEFAULT_OUTPUT="${HOME}/Downloads/${APP_NAME}.dmg"
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

echo
echo "DMG complete:"
echo "  ${OUTPUT_PATH}"
