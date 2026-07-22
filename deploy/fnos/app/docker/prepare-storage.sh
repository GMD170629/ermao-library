#!/bin/bash
set -eu

: "${TRIM_PKGVAR:?TRIM_PKGVAR 未配置}"

mkdir -p \
  "$TRIM_PKGVAR/storage/database" \
  "$TRIM_PKGVAR/storage/covers" \
  "$TRIM_PKGVAR/storage/indexes" \
  "$TRIM_PKGVAR/storage/conversions" \
  "$TRIM_PKGVAR/storage/temp/conversions" \
  "$TRIM_PKGVAR/storage/logs" \
  "$TRIM_PKGVAR/storage/secrets"
