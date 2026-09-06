#!/usr/bin/env bash
set -Eeuo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

REGISTRY="${REGISTRY:-docker.io}"
NAMESPACE="${DOCKERHUB_NAMESPACE:-${IMAGE_NAMESPACE:-gamersgu}}"
CHANNEL_TAG="${TAG:-prod}"
VERSION_TAG="${VERSION_TAG:-}"
PLATFORM="${PLATFORM:-linux/amd64,linux/arm64}"
RUN_CHECKS="${RUN_CHECKS:-true}"
NO_CACHE="${NO_CACHE:-false}"
OUTPUT_DIR=""

usage() {
  cat <<'EOF'
Publish production images to Docker Hub.

Usage:
  scripts/publish-docker-hub.sh [options]

Options:
  --namespace NAME     Docker Hub namespace/user/org. Default: gamersgu
  --tag TAG            Channel tag to update. Default: prod
  --version-tag TAG    Extra immutable tag. Default: current git short SHA
  --platform VALUE     Build platform(s). Default: linux/amd64,linux/arm64
  --registry VALUE     Registry host. Default: docker.io
  --output-dir DIR     Export an OCI archive locally; never push. Requires clean Git source.
  --skip-checks        Skip local typecheck/test/build checks before docker build
  --no-cache           Build images without Docker cache
  -h, --help           Show this help

Environment variables:
  DOCKERHUB_NAMESPACE  Same as --namespace
  IMAGE_NAMESPACE      Fallback namespace if DOCKERHUB_NAMESPACE is not set
  TAG                  Same as --tag
  VERSION_TAG          Same as --version-tag
  PLATFORM             Same as --platform
  REGISTRY             Same as --registry
  RUN_CHECKS=false     Same as --skip-checks
  NO_CACHE=true        Same as --no-cache

Examples:
  scripts/publish-docker-hub.sh
  DOCKERHUB_NAMESPACE=myname scripts/publish-docker-hub.sh
  scripts/publish-docker-hub.sh --tag prod --version-tag v0.1.15
EOF
}

while [ "$#" -gt 0 ]; do
  case "$1" in
    --namespace)
      NAMESPACE="${2:?Missing value for --namespace}"
      shift 2
      ;;
    --tag)
      CHANNEL_TAG="${2:?Missing value for --tag}"
      shift 2
      ;;
    --version-tag)
      VERSION_TAG="${2:?Missing value for --version-tag}"
      shift 2
      ;;
    --platform)
      PLATFORM="${2:?Missing value for --platform}"
      shift 2
      ;;
    --registry)
      REGISTRY="${2:?Missing value for --registry}"
      shift 2
      ;;
    --skip-checks)
      RUN_CHECKS="false"
      shift
      ;;
    --output-dir)
      OUTPUT_DIR="${2:?Missing value for --output-dir}"
      shift 2
      ;;
    --no-cache)
      NO_CACHE="true"
      shift
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "Unknown option: $1" >&2
      usage >&2
      exit 2
      ;;
  esac
done

if ! command -v docker >/dev/null 2>&1; then
  echo "docker is required but was not found in PATH." >&2
  exit 1
fi

if ! docker info >/dev/null 2>&1; then
  echo "Docker daemon is not running, or the current user cannot access it." >&2
  exit 1
fi

if ! docker buildx version >/dev/null 2>&1; then
  echo "docker buildx is required for multi-platform push builds." >&2
  exit 1
fi

if [ -z "$VERSION_TAG" ]; then
  if git rev-parse --is-inside-work-tree >/dev/null 2>&1; then
    VERSION_TAG="$(git rev-parse --short HEAD)"
  else
    VERSION_TAG="$(date +%Y%m%d%H%M%S)"
  fi
fi

if [ -z "$NAMESPACE" ]; then
  echo "Docker namespace cannot be empty." >&2
  exit 1
fi

pnpm release:validate
APP_VERSION="$(node -p "require('./package.json').version")"
if [[ "$VERSION_TAG" == v* && "$VERSION_TAG" != "v${APP_VERSION}" ]]; then
  echo "Version tag ${VERSION_TAG} does not match the validated application version v${APP_VERSION}." >&2
  exit 1
fi

IMAGE_PREFIX="${REGISTRY}/${NAMESPACE}"
BUILD_ARGS=(--platform "$PLATFORM")

require_clean_rc() {
  if [ "$(git rev-parse --verify HEAD)" != "$SOURCE_COMMIT" ] ||
     [ -n "$(git status --porcelain --untracked-files=normal)" ]; then
    echo "Local RC export requires clean committed source, including untracked files." >&2
    exit 1
  fi
}

if [ -n "$OUTPUT_DIR" ]; then
  SOURCE_COMMIT="$(git rev-parse --verify HEAD)"
  require_clean_rc
  if [[ "$OUTPUT_DIR" == *,* ]]; then
    echo "OCI output directory cannot contain a comma (Buildx output option separator)." >&2
    exit 2
  fi
  mkdir -p "$OUTPUT_DIR"
  OUTPUT_DIR="$(cd "$OUTPUT_DIR" && pwd)"
else
  BUILD_ARGS+=(--push)
fi

if [ "$NO_CACHE" = "true" ]; then
  BUILD_ARGS+=(--no-cache)
fi

run_checks() {
  echo "==> Running checks"
  pnpm --filter @shuku/web lint
  pnpm --filter @shuku/web typecheck
  pnpm --filter @shuku/web test
  pnpm --filter @shuku/web i18n:check
  pnpm --filter @shuku/web build
}

build_image() {
  local image_name="$1"
  local dockerfile="$2"
  local target="${3:-}"

  local image="${IMAGE_PREFIX}/${image_name}"
  local args=("${BUILD_ARGS[@]}" -f "$dockerfile" -t "${image}:${CHANNEL_TAG}" -t "${image}:${VERSION_TAG}")
  if [ -n "$OUTPUT_DIR" ]; then
    image="ermao-local/${image_name}:${SOURCE_COMMIT}"
    args=("${BUILD_ARGS[@]}" -f "$dockerfile" -t "$image")
  fi

  if [ -n "$target" ]; then
    args+=(--target "$target")
  fi

  if [ -n "$OUTPUT_DIR" ]; then
    # A check may regenerate tracked inputs. Do not label those changes as HEAD.
    require_clean_rc
    local archive="${OUTPUT_DIR}/${image_name}-${SOURCE_COMMIT}.oci.tar"
    if [ -e "$archive" ] || [ -e "${archive}.json" ]; then
      echo "Refusing to overwrite an existing RC artifact: ${archive}" >&2
      exit 1
    fi
    args+=(--output "type=oci,dest=${archive}")
    args+=(--label "org.opencontainers.image.revision=${SOURCE_COMMIT}")
    args+=(--label "org.opencontainers.image.version=${APP_VERSION}")
    echo "==> Exporting local OCI archive (${PLATFORM})"
  else
    echo "==> Building and pushing ${image}:${CHANNEL_TAG} (${PLATFORM})"
  fi
  if [ -n "$OUTPUT_DIR" ]; then
    # The context contains only the frozen commit, never ignored local test data,
    # credentials, previous archives or runtime caches from the worktree.
    git archive --format=tar "$SOURCE_COMMIT" | docker buildx build "${args[@]}" -
  else
    docker buildx build "${args[@]}" .
  fi
  if [ -n "$OUTPUT_DIR" ]; then
    node --input-type=module - "$archive" "$SOURCE_COMMIT" "$APP_VERSION" "$PLATFORM" "$image" <<'NODE'
import { createReadStream, writeFileSync } from 'node:fs';
import { createHash } from 'node:crypto';
import { basename } from 'node:path';
const [archive, sourceCommit, version, platforms, image] = process.argv.slice(2);
const hash = createHash('sha256');
for await (const chunk of createReadStream(archive)) hash.update(chunk);
writeFileSync(`${archive}.json`, `${JSON.stringify({
  archive: basename(archive), sha256: hash.digest('hex'), sourceCommit, version, image,
  platforms: platforms.split(','), published: false,
}, null, 2)}\n`, { flag: 'wx' });
NODE
  fi
}

if [ -n "$OUTPUT_DIR" ]; then
  echo "Preparing local OCI artifacts; no registry push"
else
  echo "Publishing Docker images"
fi
echo "  registry:     ${REGISTRY}"
echo "  namespace:    ${NAMESPACE}"
echo "  platform:     ${PLATFORM}"
echo "  channel tag:  ${CHANNEL_TAG}"
echo "  version tag:  ${VERSION_TAG}"

if [ "$RUN_CHECKS" = "true" ]; then
  run_checks
else
  echo "==> Skipping checks"
fi

build_image "shuku-starship-web" "apps/web/Dockerfile.prod" "runner"

if [ -n "$OUTPUT_DIR" ]; then
  echo "==> Local artifact and SHA-256 manifest: ${OUTPUT_DIR} (not published)"
  exit 0
fi
cat <<EOF
==> Published:
  ${IMAGE_PREFIX}/shuku-starship-web:${CHANNEL_TAG}
  ${IMAGE_PREFIX}/shuku-starship-web:${VERSION_TAG}
EOF
