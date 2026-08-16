#!/usr/bin/env bash
set -euo pipefail

readonly EXPECTED_REVISION="875172eae557a308d0c5b2be43822814c8a885bb"
readonly PDFIUM_CHECKOUT="${1:?PDFium checkout path is required}"
readonly OUTPUT_ROOT="${2:?Output root is required}"
readonly SCRIPT_DIRECTORY="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
readonly PDFIUM_DIRECTORY="$(cd "${SCRIPT_DIRECTORY}/.." && pwd)"
readonly WRAPPER_DESTINATION="${PDFIUM_CHECKOUT}/shuku_pdfium_wrapper"
readonly ROOT_BUILD_PATCH="${PDFIUM_DIRECTORY}/wrapper/root-build.patch"

[[ "$(uname -s)" == "Darwin" ]] || { echo "iOS PDFium builds require macOS" >&2; exit 2; }
[[ "$(git -C "${PDFIUM_CHECKOUT}" rev-parse HEAD)" == "${EXPECTED_REVISION}" ]] || {
  echo "PDFium checkout is not the locked revision" >&2
  exit 3
}
[[ "$(xcrun --sdk iphoneos --show-sdk-platform-path)" == *"iPhoneOS.platform" ]] || {
  echo "The physical-device iphoneos SDK is unavailable" >&2
  exit 4
}
command -v gn >/dev/null
command -v autoninja >/dev/null
command -v xcodebuild >/dev/null
[[ -z "$(git -C "${PDFIUM_CHECKOUT}" status --porcelain)" ]] || {
  echo "PDFium checkout must be clean" >&2
  exit 5
}
[[ ! -e "${WRAPPER_DESTINATION}" ]] || {
  echo "Temporary wrapper destination already exists" >&2
  exit 6
}

cleanup() {
  git -C "${PDFIUM_CHECKOUT}" apply --reverse "${ROOT_BUILD_PATCH}" 2>/dev/null || true
  rm -rf -- "${WRAPPER_DESTINATION}"
}
trap cleanup EXIT
cp -R "${PDFIUM_DIRECTORY}/wrapper" "${WRAPPER_DESTINATION}"
git -C "${PDFIUM_CHECKOUT}" apply "${ROOT_BUILD_PATCH}"

readonly OUTPUT="${OUTPUT_ROOT}/ios-arm64"
mkdir -p "${OUTPUT}"
gn gen "${OUTPUT}" --root="${PDFIUM_CHECKOUT}" --args="
  target_os=\"ios\"
  target_cpu=\"arm64\"
  is_debug=false
  is_component_build=false
  pdf_enable_v8=false
  pdf_enable_xfa=false
  pdf_use_skia=false
  pdf_enable_fontations=false
  pdf_is_standalone=false
  use_remoteexec=false
"
autoninja -C "${OUTPUT}" shuku_pdfium_wrapper:shuku_pdfium

libraries=()
while IFS= read -r path; do libraries+=("${path}"); done < <(
  find "${OUTPUT}" -type f -name 'libshuku_pdfium.a' -print
)
[[ "${#libraries[@]}" -eq 1 ]] || {
  echo "Expected one libshuku_pdfium.a, found ${#libraries[@]}" >&2
  exit 7
}

readonly ARTIFACT_DIRECTORY="${PDFIUM_DIRECTORY}/artifacts/ios"
readonly FRAMEWORK_PATH="${ARTIFACT_DIRECTORY}/ShukuPdfium.xcframework"
rm -rf -- "${FRAMEWORK_PATH}"
mkdir -p "${ARTIFACT_DIRECTORY}"
xcodebuild -create-xcframework \
  -library "${libraries[0]}" \
  -headers "${PDFIUM_DIRECTORY}/wrapper/include" \
  -output "${FRAMEWORK_PATH}"
ditto -c -k --keepParent "${FRAMEWORK_PATH}" \
  "${ARTIFACT_DIRECTORY}/ShukuPdfium.xcframework.zip"
"${SCRIPT_DIRECTORY}/package-licenses.sh" "${PDFIUM_CHECKOUT}" "${PDFIUM_DIRECTORY}/artifacts"

git -C "${PDFIUM_CHECKOUT}" apply --reverse "${ROOT_BUILD_PATCH}"
rm -rf -- "${WRAPPER_DESTINATION}"

[[ -z "$(git -C "${PDFIUM_CHECKOUT}" status --porcelain --untracked-files=no)" ]] || {
  echo "PDFium checkout changed during the build" >&2
  exit 8
}
