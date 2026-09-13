#!/usr/bin/env bash
set -euo pipefail

# Never enable shell tracing: signing material is supplied only through env.
channel="${3:-beta}"
case "$channel" in
  beta) prefix=BETA ;;
  stable) prefix=RELEASE ;;
  *) echo 'Unknown signing channel' >&2; exit 1 ;;
esac
for suffix in KEYSTORE_BASE64 KEYSTORE_PASSWORD KEY_ALIAS KEY_PASSWORD; do
  source_name="${prefix}_${suffix}"
  [[ -n "${!source_name:-}" ]] || { echo "Required signing input is missing: $source_name" >&2; exit 1; }
  export "ANDROID_SIGNING_${suffix}=${!source_name}"
done
input_dir="${1:?unsigned APK directory required}"
output_dir="${2:?signed APK directory required}"
tools="${ANDROID_HOME:?}/build-tools/36.0.0"
temporary="$(mktemp -d)"
trap 'rm -rf -- "$temporary"' EXIT
chmod 700 "$temporary"
printf '%s' "$ANDROID_SIGNING_KEYSTORE_BASE64" | base64 --decode > "$temporary/signing.p12"
chmod 600 "$temporary/signing.p12"
shopt -s nullglob
apks=("$input_dir"/*.apk)
[[ ${#apks[@]} -eq 1 ]] || { echo 'Expected exactly one APK' >&2; exit 1; }
badging="$("$tools/aapt" dump badging "${apks[0]}")"
version="$(sed -n "s/^package: .*versionName='\([^']*\)'.*/\1/p" <<< "$badging")"
if [[ "$channel" == beta ]]; then
  : "${GITHUB_RUN_NUMBER:?}" "${GITHUB_RUN_ATTEMPT:?}" "${GITHUB_SHA:?}"
  code=$((100000 + GITHUB_RUN_NUMBER))
  grep -q "^package: name='com.ermao.library.beta' versionCode='$code'" <<< "$badging"
  [[ "$version" == *"-beta.$GITHUB_RUN_NUMBER" ]]
  name="ermao-library-$version-${GITHUB_SHA:0:8}-r$GITHUB_RUN_ATTEMPT.apk"
else
  expected="$(node -p "require('./package.json').version")"
  code="$(sed -n 's/^[[:space:]]*versionCode = \([0-9]*\).*/\1/p' apps/mobile/androidApp/build.gradle.kts)"
  [[ "$version" == "$expected" ]]
  grep -q "^package: name='com.ermao.library' versionCode='$code'" <<< "$badging"
  name="ermao-library-v$version-android.apk"
fi
if grep -q '^application-debuggable' <<< "$badging"; then
  echo 'Refusing to publish a debuggable APK' >&2
  exit 1
fi
mkdir -p "$output_dir"
"$tools/zipalign" -P 16 -f 4 "${apks[0]}" "$temporary/aligned.apk"
"$tools/apksigner" sign --ks "$temporary/signing.p12" --ks-key-alias "$ANDROID_SIGNING_KEY_ALIAS" \
  --ks-pass env:ANDROID_SIGNING_KEYSTORE_PASSWORD --key-pass env:ANDROID_SIGNING_KEY_PASSWORD \
  --v4-signing-enabled false --out "$output_dir/$name" "$temporary/aligned.apk"
"$tools/zipalign" -c -P 16 4 "$output_dir/$name"
"$tools/apksigner" verify --verbose --print-certs "$output_dir/$name" > "$temporary/signature.txt"
keytool -exportcert -keystore "$temporary/signing.p12" -storepass:env ANDROID_SIGNING_KEYSTORE_PASSWORD \
  -alias "$ANDROID_SIGNING_KEY_ALIAS" -file "$temporary/certificate.der" 2>/dev/null
certificate="$(sha256sum "$temporary/certificate.der" | cut -d' ' -f1)"
grep -qi "Signer #1 certificate SHA-256 digest: $certificate" "$temporary/signature.txt"
(cd "$output_dir" && sha256sum "$name" > "$name.sha256")
echo "Verified $channel APK: $name (versionCode $code)"
echo "Certificate SHA-256: $certificate"
