#!/bin/zsh
set -euo pipefail

SCRIPT_DIR="${0:A:h}"
POC_ROOT="${SCRIPT_DIR:h}"
REPO_ROOT="${POC_ROOT:h:h:h}"
CALIBRE_APP="${CALIBRE_APP:-/Applications/calibre.app}"
EBOOK_CONVERT="${CALIBRE_APP}/Contents/MacOS/ebook-convert"
EXPECTED_VERSION="9.11.0"
export SOURCE_DATE_EPOCH="1767225600"
export TZ="UTC"
WORK_ROOT="${POC_ROOT}/.fixture-build"
SOURCE_ROOT="${POC_ROOT}/Fixtures/Sources/Generated"
EPUB_ROOT="${WORK_ROOT}/epub"
FIXTURE_ROOT="${REPO_ROOT}/test-data/library/mobi"
FONT_FILE="${POC_ROOT}/Fixtures/Sources/Assets/Literata-Regular.ttf"

if [[ ! -x "${EBOOK_CONVERT}" ]]; then
  print -u2 "ebook-convert not found at ${EBOOK_CONVERT}"
  exit 1
fi

CALIBRE_VERSION="$(${EBOOK_CONVERT} --version | head -n 1 | awk '{print $NF}' | tr -d ')')"
if [[ "${CALIBRE_VERSION}" != "${EXPECTED_VERSION}" ]]; then
  print -u2 "Calibre ${EXPECTED_VERSION} is required; found ${CALIBRE_VERSION}"
  exit 1
fi

mkdir -p "${WORK_ROOT}" "${SOURCE_ROOT}" "${EPUB_ROOT}" "${FIXTURE_ROOT}"
swiftc "${SCRIPT_DIR}/GenerateFixtureSources.swift" -o "${WORK_ROOT}/generate-fixture-sources"
"${WORK_ROOT}/generate-fixture-sources" "${SOURCE_ROOT}" "${FONT_FILE}"
find "${SOURCE_ROOT}" -exec touch -t 202601010000 {} +

typeset -A OUTPUTS
OUTPUTS[01-basic-mobi6]="01-basic-mobi6.mobi"
OUTPUTS[02-basic-kf8]="test.azw3"
OUTPUTS[03-css]="03-css.azw3"
OUTPUTS[04-font]="04-font.azw3"
OUTPUTS[05-images]="05-images.azw3"
OUTPUTS[06-footnotes]="06-footnotes.azw3"
OUTPUTS[07-complex-toc]="07-complex-toc.azw3"
OUTPUTS[08-zh-hans]="08-zh-hans.azw3"
OUTPUTS[09-ja-vertical]="09-ja-vertical.azw3"
OUTPUTS[10-long-chapter]="10-long-chapter.azw3"

for fixture_id in ${(ko)OUTPUTS}; do
  source_dir="${SOURCE_ROOT}/${fixture_id}"
  epub_file="${EPUB_ROOT}/${fixture_id}.epub"
  output_file="${FIXTURE_ROOT}/${OUTPUTS[${fixture_id}]}"
  rm -f "${epub_file}"
  (
    cd "${source_dir}"
    /usr/bin/zip -X0q "${epub_file}" mimetype
    /usr/bin/zip -X9qr "${epub_file}" META-INF OEBPS
  )
  if [[ "${fixture_id}" == "01-basic-mobi6" ]]; then
    "${EBOOK_CONVERT}" "${epub_file}" "${output_file}" --mobi-file-type old --no-inline-toc
  else
    "${EBOOK_CONVERT}" "${epub_file}" "${output_file}" --no-inline-toc
  fi
done

(
  cd "${FIXTURE_ROOT}"
  shasum -a 256 01-basic-mobi6.mobi test.azw3 03-css.azw3 04-font.azw3 05-images.azw3 06-footnotes.azw3 07-complex-toc.azw3 08-zh-hans.azw3 09-ja-vertical.azw3 10-long-chapter.azw3 > SHA256SUMS
)
cp "${POC_ROOT}/Fixtures/fixture-expectations.json" "${FIXTURE_ROOT}/fixture-expectations.json"

(
  cd "${SOURCE_ROOT}"
  find . -type f | LC_ALL=C sort | xargs shasum -a 256 > "${POC_ROOT}/Fixtures/Sources/SHA256SUMS"
)

print "Generated 10 fixed fixtures with Calibre ${EXPECTED_VERSION}."
