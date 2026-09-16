#!/usr/bin/env bash
# Runs only during release packaging, against the exact immutable target image.
set -euo pipefail
image="${1:?usage: build-release-app-packages.sh IMAGE@sha256:DIGEST OUTPUT}"
output="${2:?output required}"
[[ "$image" =~ @sha256:[a-f0-9]{64}$ ]] || { echo 'An immutable image digest is required' >&2; exit 1; }
mkdir -p "$output"
output="$(cd "$output" && pwd)"
repo="$(cd "$(dirname "$0")/.." && pwd)"
for architecture in amd64 arm64; do
  docker run --rm --platform "linux/$architecture" --entrypoint python \
    -v "$repo/scripts/build-application-package.py:/opt/shuku-image/scripts/build-application-package.py:ro" \
    -v "$output:/packages" "$image" \
    /opt/shuku-image/scripts/build-application-package.py --program-root /opt/shuku-image --output-dir /packages
  # Validate by the production extractor inside that SAME fixed target environment.
  docker run --rm --platform "linux/$architecture" --entrypoint python \
    -e PYTHONPATH=/opt/shuku-image/apps/api-python -v "$output:/packages:ro" "$image" -c '
import json, pathlib, tempfile
from threading import Event
from app.modules.updates.public import Package
from app.modules.updates.infrastructure.archive import extract_package
identity = json.loads(pathlib.Path("/opt/shuku-image/application.json").read_text())
fixed = json.loads(pathlib.Path("/opt/shuku-launcher/environment.json").read_text())["environment"]
assert identity["environment"] == fixed
name = "shuku-" + identity["version"] + "-" + fixed["platform"] + ".tar.gz"
package = Package.model_validate_json(pathlib.Path("/packages", name + ".json").read_bytes())
assert package.environment.model_dump() == fixed
with tempfile.TemporaryDirectory() as directory:
    extract_package(pathlib.Path("/packages", name), pathlib.Path(directory) / "app", package, Event())
'
done
