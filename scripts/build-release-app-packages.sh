#!/usr/bin/env bash
# Runs only during release packaging, against the exact immutable target image.
set -euo pipefail
image="${1:?usage: build-release-app-packages.sh IMAGE@sha256:DIGEST OUTPUT}"
output="${2:?output required}"
[[ "$image" =~ @sha256:[a-f0-9]{64}$ ]] || { echo 'An immutable image digest is required' >&2; exit 1; }
mkdir -p "$output"
output="$(cd "$output" && pwd)"
repo="$(cd "$(dirname "$0")/.." && pwd)"
staging="$(mktemp -d)"
trap 'rm -rf "$staging"' EXIT
docker buildx imagetools inspect "$image" --raw > "$staging/image-index.json"
for architecture in amd64 arm64; do
  platform_digest="$(node - "$staging/image-index.json" "$architecture" <<'NODE'
const fs = require('node:fs');
const index = JSON.parse(fs.readFileSync(process.argv[2], 'utf8'));
const matches = (index.manifests ?? []).filter(manifest =>
  manifest.platform?.os === 'linux' && manifest.platform?.architecture === process.argv[3]
  && manifest.annotations?.['vnd.docker.reference.type'] !== 'attestation-manifest');
if (matches.length !== 1 || !/^sha256:[a-f0-9]{64}$/.test(matches[0].digest)) {
  throw new Error(`Expected one immutable linux/${process.argv[3]} image manifest`);
}
process.stdout.write(matches[0].digest);
NODE
  )"
  platform_image="${image%@*}@$platform_digest"
  mkdir "$staging/$architecture"
  docker run --rm --network none --platform "linux/$architecture" --entrypoint /bin/sh \
    -v "$repo/scripts/build-application-package.py:/opt/shuku-image/scripts/build-application-package.py:ro" \
    -v "$staging/$architecture:/packages" "$platform_image" -ec '
    # Tool-only venv, outside both the fixed launcher and persistent business venv.
    uv --offline --no-cache --no-config --no-python-downloads venv --python /usr/local/bin/python3.11 /tmp/package-tools
    uv --offline --no-cache --no-config --no-python-downloads pip install --python /tmp/package-tools/bin/python --no-index --no-deps --no-build /opt/shuku-dependency-seed/wheels/*.whl
    /tmp/package-tools/bin/python /opt/shuku-image/scripts/build-application-package.py \
      --program-root /opt/shuku-image --output-dir /packages \
      --dependency-seed /opt/shuku-dependency-seed \
      --fixed-environment /opt/shuku-launcher/environment.json --verify
    rm /packages/*-code.tar.gz.json
  '
done
node "$repo/scripts/validate-app-packages.mjs" --merge "$output" "$staging/amd64" "$staging/arm64"
