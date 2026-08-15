#!/usr/bin/env bash
set -euo pipefail

readonly EXPECTED_REVISION="875172eae557a308d0c5b2be43822814c8a885bb"
readonly PDFIUM_CHECKOUT="${1:?PDFium checkout path is required}"
readonly OUTPUT_ROOT="${2:?Output root is required}"
readonly SCRIPT_DIRECTORY="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
readonly PDFIUM_DIRECTORY="$(cd "${SCRIPT_DIRECTORY}/.." && pwd)"
readonly MOBILE_DIRECTORY="$(cd "${PDFIUM_DIRECTORY}/../.." && pwd)"
readonly WRAPPER_DESTINATION="${PDFIUM_CHECKOUT}/shuku_pdfium_wrapper"
readonly JNI_DESTINATION="${PDFIUM_DIRECTORY}/artifacts/android/jni"

[[ "$(uname -s)" == "Linux" ]] || { echo "Android PDFium builds require Linux" >&2; exit 2; }
[[ "$(git -C "${PDFIUM_CHECKOUT}" rev-parse HEAD)" == "${EXPECTED_REVISION}" ]] || {
  echo "PDFium checkout is not the locked revision" >&2
  exit 3
}
command -v gn >/dev/null
command -v autoninja >/dev/null
[[ -z "$(git -C "${PDFIUM_CHECKOUT}" status --porcelain)" ]] || {
  echo "PDFium checkout must be clean" >&2
  exit 4
}
[[ ! -e "${WRAPPER_DESTINATION}" ]] || {
  echo "Temporary wrapper destination already exists" >&2
  exit 5
}

cleanup() {
  rm -rf -- "${WRAPPER_DESTINATION}"
}
trap cleanup EXIT
cp -R "${PDFIUM_DIRECTORY}/wrapper" "${WRAPPER_DESTINATION}"
rm -rf -- "${JNI_DESTINATION}"
mkdir -p "${JNI_DESTINATION}"

configure() {
  local abi="$1"
  local cpu="$2"
  local output="${OUTPUT_ROOT}/${abi}"
  mkdir -p "${output}"
  gn gen "${output}" --root="${PDFIUM_CHECKOUT}" --args="
    target_os=\"android\"
    target_cpu=\"${cpu}\"
    is_debug=false
    is_component_build=false
    pdf_enable_v8=false
    pdf_enable_xfa=false
    pdf_use_skia=false
    pdf_enable_fontations=false
    pdf_is_standalone=false
    use_remoteexec=false
  "
  autoninja -C "${output}" shuku_pdfium_wrapper:shuku_pdfium
  local libraries=()
  while IFS= read -r path; do libraries+=("${path}"); done < <(
    find "${output}" -type f -name 'libshuku_pdfium.so' -print
  )
  [[ "${#libraries[@]}" -eq 1 ]] || {
    echo "Expected one libshuku_pdfium.so for ${abi}, found ${#libraries[@]}" >&2
    exit 6
  }
  mkdir -p "${JNI_DESTINATION}/${abi}"
  cp "${libraries[0]}" "${JNI_DESTINATION}/${abi}/libshuku_pdfium.so"
}

configure arm64-v8a arm64
configure armeabi-v7a arm
configure x86_64 x64

"${MOBILE_DIRECTORY}/gradlew" -p "${MOBILE_DIRECTORY}" :pdfiumNative:assembleRelease
mkdir -p "${PDFIUM_DIRECTORY}/artifacts/android"
cp "${MOBILE_DIRECTORY}/pdfiumNative/build/outputs/aar/pdfiumNative-release.aar" \
  "${PDFIUM_DIRECTORY}/artifacts/android/shuku-pdfium.aar"
"${SCRIPT_DIRECTORY}/package-licenses.sh" "${PDFIUM_CHECKOUT}" "${PDFIUM_DIRECTORY}/artifacts"

[[ -z "$(git -C "${PDFIUM_CHECKOUT}" status --porcelain --untracked-files=no)" ]] || {
  echo "PDFium checkout changed during the build" >&2
  exit 7
}
