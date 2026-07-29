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
BUILD_ARGS=(--platform "$PLATFORM" --push)

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

  if [ -n "$target" ]; then
    args+=(--target "$target")
  fi

  echo "==> Building and pushing ${image}:${CHANNEL_TAG} (${PLATFORM})"
  docker buildx build "${args[@]}" .
}

echo "Publishing Docker images"
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

cat <<EOF
==> Published:
  ${IMAGE_PREFIX}/shuku-starship-web:${CHANNEL_TAG}
  ${IMAGE_PREFIX}/shuku-starship-web:${VERSION_TAG}
EOF
