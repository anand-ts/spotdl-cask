#!/usr/bin/env bash

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PYTHON_BIN="${ROOT_DIR}/.venv/bin/python"
SPEC_DIR="${ROOT_DIR}/build/spec"
ICON_ICNS="${ROOT_DIR}/assets/macos/spotdl-web-downloader.icns"
export PYINSTALLER_CONFIG_DIR="${ROOT_DIR}/.pyinstaller"

if [[ ! -x "${PYTHON_BIN}" ]]; then
    echo "Missing ${PYTHON_BIN}. Run './setup --group dev' first."
    exit 1
fi

if [[ ! -f "${ICON_ICNS}" ]]; then
    echo "Missing ${ICON_ICNS}. Generate it with 'python3 tools/generate_macos_icon.py' first."
    exit 1
fi

eval "$(
    "${PYTHON_BIN}" - <<'PY'
import shlex
from project_meta import APP_CATEGORY, APP_COPYRIGHT, APP_NAME, APP_VERSION, BUNDLE_ID

payload = {
    "APP_NAME": APP_NAME,
    "APP_VERSION": APP_VERSION,
    "BUNDLE_ID": BUNDLE_ID,
    "APP_CATEGORY": APP_CATEGORY,
    "APP_COPYRIGHT": APP_COPYRIGHT,
}
for key, value in payload.items():
    print(f"{key}={shlex.quote(str(value))}")
PY
)"

APP_PATH="${ROOT_DIR}/dist/${APP_NAME}.app"
APP_EXECUTABLE="${APP_PATH}/Contents/MacOS/${APP_NAME}"
INFO_PLIST="${APP_PATH}/Contents/Info.plist"
ICON_FILENAME="$(basename "${ICON_ICNS}")"
SIGNING_IDENTITY="${MACOS_CODESIGN_IDENTITY:--}"
PYINSTALLER_ARGS=(
    --noconfirm
    --windowed
    --name "${APP_NAME}"
    --icon "${ICON_ICNS}"
    --osx-bundle-identifier "${BUNDLE_ID}"
    --specpath "${SPEC_DIR}"
    --collect-data pykakasi
    --add-data "${ROOT_DIR}/templates:templates"
    --add-data "${ROOT_DIR}/static:static"
)

mkdir -p "${SPEC_DIR}"

apply_bundle_metadata() {
    plutil -replace CFBundleDisplayName -string "${APP_NAME}" "${INFO_PLIST}"
    plutil -replace CFBundleName -string "${APP_NAME}" "${INFO_PLIST}"
    plutil -replace CFBundleIdentifier -string "${BUNDLE_ID}" "${INFO_PLIST}"
    plutil -replace CFBundleShortVersionString -string "${APP_VERSION}" "${INFO_PLIST}"
    plutil -replace CFBundleVersion -string "${APP_VERSION}" "${INFO_PLIST}"
    plutil -replace CFBundleIconFile -string "${ICON_FILENAME}" "${INFO_PLIST}"
    plutil -replace LSApplicationCategoryType -string "${APP_CATEGORY}" "${INFO_PLIST}"
    plutil -replace NSHumanReadableCopyright -string "${APP_COPYRIGHT}" "${INFO_PLIST}"
}

sign_bundle() {
    local sign_args=(
        --force
        --sign "${SIGNING_IDENTITY}"
    )
    if [[ -n "${MACOS_ENTITLEMENTS_FILE:-}" ]]; then
        sign_args+=(--entitlements "${MACOS_ENTITLEMENTS_FILE}")
    fi
    if [[ "${SIGNING_IDENTITY}" != "-" ]]; then
        sign_args+=(--options runtime)
    fi

    echo "Signing app bundle with identity: ${SIGNING_IDENTITY}"

    while IFS= read -r sign_target; do
        codesign "${sign_args[@]}" "${sign_target}"
    done < <(
        find "${APP_PATH}/Contents/Frameworks" "${APP_PATH}/Contents/MacOS" \
            -type f \
            \( -name '*.dylib' -o -name '*.so' -o -path '*/bin/*' -o -perm -111 \) \
            | sort
    )

    codesign "${sign_args[@]}" "${APP_PATH}"
}

for binary_name in ffmpeg ffprobe; do
    if binary_path="$(command -v "${binary_name}" 2>/dev/null)"; then
        echo "Bundling ${binary_name} from ${binary_path}"
        PYINSTALLER_ARGS+=(--add-binary "${binary_path}:bin")
    else
        echo "Warning: ${binary_name} was not found on PATH while building."
        echo "         The exported app will rely on runtime discovery instead."
    fi
done

verify_bundle() {
    local required_paths=(
        "${APP_EXECUTABLE}"
        "${APP_PATH}/Contents/Frameworks/bin/ffmpeg"
        "${APP_PATH}/Contents/Frameworks/bin/ffprobe"
        "${APP_PATH}/Contents/Resources/templates/index.html"
        "${APP_PATH}/Contents/Resources/static/css/style.css"
        "${APP_PATH}/Contents/Resources/static/css/sections/tokens.css"
        "${APP_PATH}/Contents/Resources/static/js/app.js"
        "${APP_PATH}/Contents/Resources/static/js/modules/bootstrap.js"
        "${APP_PATH}/Contents/Resources/static/favicon.svg"
    )

    echo
    echo "Verifying bundled app contents..."
    for required_path in "${required_paths[@]}"; do
        if [[ ! -e "${required_path}" ]]; then
            echo "Missing required bundled asset: ${required_path}"
            exit 1
        fi
    done

    echo "Checking bundled ffmpeg..."
    "${APP_PATH}/Contents/Frameworks/bin/ffmpeg" -version >/dev/null

    echo "Checking bundled spotDL helper..."
    env PATH=/usr/bin:/bin HOME="${HOME}" \
        "${APP_EXECUTABLE}" \
        --run-spotdl \
        --version >/dev/null

    echo "Verifying bundle signature..."
    codesign --verify --deep --strict "${APP_PATH}"
}

"${PYTHON_BIN}" -m PyInstaller \
    "${PYINSTALLER_ARGS[@]}" \
    "${ROOT_DIR}/app.py"

apply_bundle_metadata
sign_bundle

verify_bundle

echo
echo "Build complete and verified:"
echo "  ${APP_PATH}"
