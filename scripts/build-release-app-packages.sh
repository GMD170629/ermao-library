#!/usr/bin/env bash
# Runs only during release packaging, against the exact immutable target image.
set -euo pipefail
image="${1:?usage: build-release-app-packages.sh IMAGE@sha256:DIGEST OUTPUT}"
output="${2:?output required}"
[[ "$image" =~ @sha256:[a-f0-9]{64}$ ]] || { echo 'An immutable image digest is required' >&2; exit 1; }
mode="${3:-full}"
seed_version="${4:-}"
[[ "$mode" == full || "$mode" == code-only ]] || { echo 'Invalid release mode' >&2; exit 1; }
if [[ "$mode" == code-only ]]; then
  [[ "$seed_version" =~ ^[0-9]+\.[0-9]+\.[0-9]+$ ]] || { echo 'Baseline seed version required' >&2; exit 1; }
fi
mkdir -p "$output"
output="$(cd "$output" && pwd)"
repo="$(cd "$(dirname "$0")/.." && pwd)"
staging="$(mktemp -d)"
trap 'rm -rf "$staging"' EXIT
if [[ "$mode" == code-only ]]; then
  # Copy only versioned source, excluding unrelated Wiki; never host build output.
  python3 - "$repo" "$staging/source" <<'PYCODE'
import pathlib, shutil, subprocess, sys
root, target = map(pathlib.Path, sys.argv[1:])
for name in subprocess.check_output(['git', '-C', str(root), 'ls-files', '-z']).decode().split('\0'):
    if not name or name == 'ermao-library.wiki' or name.startswith('ermao-library.wiki/'): continue
    source = root / name
    if not source.is_file() and not source.is_symlink(): continue
    destination = target / name
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, destination, follow_symlinks=False)
PYCODE
fi
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
  if [[ "$mode" == code-only ]]; then
    docker run --rm --platform "linux/$architecture" --entrypoint /usr/local/bin/python3.11 \
      -e "SHUKU_SEED_VERSION=$seed_version" \
      -v "$staging/source:/source:ro" -v "$staging/$architecture:/packages" \
      -v "$repo/scripts/build-code-only-app.py:/build-code-only-app.py:ro" \
      "$platform_image" /build-code-only-app.py
    rm "$staging/$architecture/"*-code.tar.gz.json
    continue
  fi
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
