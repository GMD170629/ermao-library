#!/usr/bin/env bash
set -euo pipefail

readonly PDFIUM_CHECKOUT="${1:?PDFium checkout path is required}"
readonly ARTIFACT_ROOT="${2:?Artifact root is required}"
readonly LICENSE_ROOT="${ARTIFACT_ROOT}/licenses"
readonly NOTICES="${LICENSE_ROOT}/THIRD_PARTY_NOTICES.txt"

[[ -f "${PDFIUM_CHECKOUT}/LICENSE" ]] || {
  echo "PDFium LICENSE is missing" >&2
  exit 2
}

rm -rf -- "${LICENSE_ROOT}"
mkdir -p "${LICENSE_ROOT}"
cp "${PDFIUM_CHECKOUT}/LICENSE" "${LICENSE_ROOT}/PDFIUM_LICENSE.txt"
: > "${NOTICES}"

while IFS= read -r -d '' notice; do
  relative="${notice#${PDFIUM_CHECKOUT}/}"
  printf '\n===== %s =====\n' "${relative}" >> "${NOTICES}"
  cat "${notice}" >> "${NOTICES}"
  printf '\n' >> "${NOTICES}"
done < <(
  find "${PDFIUM_CHECKOUT}/third_party" -type f \
    \( -name 'LICENSE' -o -name 'LICENSE.*' -o -name 'COPYING' -o -name 'COPYING.*' -o -name 'README.pdfium' \) \
    -print0 | sort -z
)

[[ -s "${NOTICES}" ]] || {
  echo "PDFium third-party notice bundle is empty" >&2
  exit 3
}
