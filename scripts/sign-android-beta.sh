#!/usr/bin/env bash
set -euo pipefail

# Never enable shell tracing: signing material is supplied only through env.
for name in BETA_KEYSTORE_BASE64 BETA_KEYSTORE_PASSWORD BETA_KEY_ALIAS BETA_KEY_PASSWORD GITHUB_RUN_NUMBER GITHUB_RUN_ATTEMPT GITHUB_SHA; do
  if [[ -z "${!name:-}" ]]; then
    echo "Required beta signing input is missing: $name" >&2
    exit 1
  fi
done
input_dir="${1:?unsigned APK directory required}"
output_dir="${2:?signed APK directory required}"
tools="${ANDROID_HOME:?}/build-tools/36.0.0"
temporary="$(mktemp -d)"
trap 'rm -rf -- "$temporary"' EXIT
chmod 700 "$temporary"
printf '%s' "$BETA_KEYSTORE_BASE64" | base64 --decode > "$temporary/beta.p12"
chmod 600 "$temporary/beta.p12"
shopt -s nullglob
apks=("$input_dir"/*.apk)
[[ ${#apks[@]} -eq 1 ]] || { echo 'Expected exactly one beta APK' >&2; exit 1; }
badging="$("$tools/aapt" dump badging "${apks[0]}")"
version="$(sed -n "s/^package: .*versionName='\([^']*\)'.*/\1/p" <<< "$badging")"
code=$((100000 + GITHUB_RUN_NUMBER))
grep -q "^package: name='com.ermao.library.beta' versionCode='$code'" <<< "$badging"
[[ "$version" == *"-beta.$GITHUB_RUN_NUMBER" ]]
if grep -q '^application-debuggable' <<< "$badging"; then
  echo 'Refusing to publish a debuggable beta APK' >&2
  exit 1
fi
mkdir -p "$output_dir"
name="ermao-library-$version-${GITHUB_SHA:0:8}-r$GITHUB_RUN_ATTEMPT.apk"
"$tools/zipalign" -P 16 -f 4 "${apks[0]}" "$temporary/aligned.apk"
"$tools/apksigner" sign --ks "$temporary/beta.p12" --ks-key-alias "$BETA_KEY_ALIAS" \
  --ks-pass env:BETA_KEYSTORE_PASSWORD --key-pass env:BETA_KEY_PASSWORD \
  --out "$output_dir/$name" "$temporary/aligned.apk"
"$tools/zipalign" -c -P 16 4 "$output_dir/$name"
"$tools/apksigner" verify --verbose --print-certs "$output_dir/$name" > "$temporary/signature.txt"
keytool -exportcert -keystore "$temporary/beta.p12" -storepass:env BETA_KEYSTORE_PASSWORD \
  -alias "$BETA_KEY_ALIAS" -file "$temporary/certificate.der" 2>/dev/null
certificate="$(sha256sum "$temporary/certificate.der" | cut -d' ' -f1)"
grep -qi "Signer #1 certificate SHA-256 digest: $certificate" "$temporary/signature.txt"
(cd "$output_dir" && sha256sum "$name" > "$name.sha256")
echo "Verified beta APK: $name (versionCode $code)"
echo "Certificate SHA-256: $certificate"
