#!/usr/bin/env bash
set -euo pipefail

readonly WRAPPER_DIRECTORY="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
readonly PDFIUM_HEADERS="${WRAPPER_DIRECTORY}/../../artifacts/ios/Pdfium.xcframework/ios-arm64/Headers"
readonly TEST_BINARY="$(mktemp "${TMPDIR:-/tmp}/shuku-pdfium-thread-test.XXXXXX")"
trap 'rm -f -- "${TEST_BINARY}"' EXIT

c++ \
  -std=c++17 \
  -Wall \
  -Wextra \
  -Werror \
  -pthread \
  -I"${WRAPPER_DIRECTORY}/host_tests/include" \
  -I"${WRAPPER_DIRECTORY}/include" \
  -I"${PDFIUM_HEADERS}" \
  "${WRAPPER_DIRECTORY}/src/shuku_pdfium.cc" \
  "${WRAPPER_DIRECTORY}/host_tests/shuku_pdfium_thread_safety_test.cc" \
  -o "${TEST_BINARY}"

"${TEST_BINARY}"
