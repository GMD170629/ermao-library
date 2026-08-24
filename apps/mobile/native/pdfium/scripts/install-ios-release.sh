#!/usr/bin/env bash
set -euo pipefail

readonly PDFIUM_RELEASE="153.0.8009.0"
readonly PDFIUM_BRANCH="8009"
readonly PDFIUM_SHA256="671ae30cc2ed65d0adf4a32d176bfcc9fe800da6237659d2b5a8e18832bf7cac"
readonly IOS_DEPLOYMENT_TARGET="17.0"
readonly SCRIPT_DIRECTORY="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
readonly PDFIUM_DIRECTORY="$(cd "${SCRIPT_DIRECTORY}/.." && pwd)"
readonly ARCHIVE_NAME="pdfium-ios-device-arm64.tgz"
readonly RELEASE_URL="https://github.com/bblanchon/pdfium-binaries/releases/download/chromium%2F${PDFIUM_BRANCH}/${ARCHIVE_NAME}"
readonly WORK_DIRECTORY="$(mktemp -d /tmp/shuku-pdfium-release.XXXXXX)"

cleanup() {
  rm -rf -- "${WORK_DIRECTORY}"
}
trap cleanup EXIT

readonly ARCHIVE_PATH="${WORK_DIRECTORY}/${ARCHIVE_NAME}"
readonly PACKAGE_DIRECTORY="${WORK_DIRECTORY}/package"
readonly INCLUDE_ROOT="${WORK_DIRECTORY}/include-root"
readonly WRAPPER_BUILD="${WORK_DIRECTORY}/wrapper"
readonly ARTIFACT_DIRECTORY="${PDFIUM_DIRECTORY}/artifacts/ios"
readonly STAGED_ARTIFACTS="${WORK_DIRECTORY}/artifacts"

curl -fL --retry 3 "${RELEASE_URL}" -o "${ARCHIVE_PATH}"
echo "${PDFIUM_SHA256}  ${ARCHIVE_PATH}" | shasum -a 256 -c -
mkdir -p "${PACKAGE_DIRECTORY}" "${INCLUDE_ROOT}" "${WRAPPER_BUILD}" "${STAGED_ARTIFACTS}"
tar -xzf "${ARCHIVE_PATH}" -C "${PACKAGE_DIRECTORY}"
ln -s "${PACKAGE_DIRECTORY}/include" "${INCLUDE_ROOT}/public"

vtool -show-build "${PACKAGE_DIRECTORY}/lib/libpdfium.dylib" | grep -q "minos ${IOS_DEPLOYMENT_TARGET}"
xcrun --sdk iphoneos clang++ \
  -arch arm64 -miphoneos-version-min="${IOS_DEPLOYMENT_TARGET}" -std=c++20 -fvisibility=hidden \
  -I "${PDFIUM_DIRECTORY}/wrapper/include" -I "${INCLUDE_ROOT}" \
  -c "${PDFIUM_DIRECTORY}/wrapper/src/shuku_pdfium.cc" \
  -o "${WRAPPER_BUILD}/shuku_pdfium.o"
xcrun --sdk iphoneos clang++ \
  -arch arm64 -miphoneos-version-min="${IOS_DEPLOYMENT_TARGET}" -std=c++20 -fvisibility=hidden \
  -DSHUKU_PDFIUM_RELEASE=\"${PDFIUM_RELEASE}\" \
  -I "${PDFIUM_DIRECTORY}/wrapper/include" \
  -c "${PDFIUM_DIRECTORY}/wrapper/src/shuku_pdfium_revision.cc" \
  -o "${WRAPPER_BUILD}/shuku_pdfium_revision.o"
xcrun libtool -static \
  -o "${WRAPPER_BUILD}/libShukuPdfium.a" \
  "${WRAPPER_BUILD}/shuku_pdfium.o" "${WRAPPER_BUILD}/shuku_pdfium_revision.o"

cp "${PACKAGE_DIRECTORY}/lib/libpdfium.dylib" "${STAGED_ARTIFACTS}/libpdfium.dylib"
install_name_tool -id "@rpath/libpdfium.dylib" "${STAGED_ARTIFACTS}/libpdfium.dylib"
xcodebuild -create-xcframework \
  -library "${STAGED_ARTIFACTS}/libpdfium.dylib" \
  -headers "${PACKAGE_DIRECTORY}/include" \
  -output "${STAGED_ARTIFACTS}/Pdfium.xcframework"
xcodebuild -create-xcframework \
  -library "${WRAPPER_BUILD}/libShukuPdfium.a" \
  -headers "${PDFIUM_DIRECTORY}/wrapper/include" \
  -output "${STAGED_ARTIFACTS}/ShukuPdfium.xcframework"

mkdir -p "${ARTIFACT_DIRECTORY}"
for artifact in Pdfium.xcframework ShukuPdfium.xcframework; do
  rm -rf -- "${ARTIFACT_DIRECTORY}/${artifact}"
  mv "${STAGED_ARTIFACTS}/${artifact}" "${ARTIFACT_DIRECTORY}/${artifact}"
done
