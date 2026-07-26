#!/bin/sh
set -eu

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT_DIR"

CHILD_PIDS=""
MANAGED_POSTGRES_CONTAINER=""

cleanup() {
  trap - INT TERM EXIT
  for pid in $CHILD_PIDS; do
    if kill -0 "$pid" 2>/dev/null; then
      pkill -TERM -P "$pid" 2>/dev/null || true
      kill -TERM "$pid" 2>/dev/null || true
    fi
  done
  for pid in $CHILD_PIDS; do
    wait "$pid" 2>/dev/null || true
  done
  if [ -n "$MANAGED_POSTGRES_CONTAINER" ]; then
    docker stop "$MANAGED_POSTGRES_CONTAINER" >/dev/null 2>&1 || true
  fi
}
trap cleanup INT TERM EXIT

if [ -f .env ]; then
  set -a
  # shellcheck disable=SC1091
  . ./.env
  set +a
fi

PYTHON_API_PORT="8000"
WEB_PORT="${WEB_PORT:-3000}"
WEB_HOST="${WEB_HOST:-0.0.0.0}"
WEB_MODE="${WEB_MODE:-dev}"
APPV2_MIGRATE_MODULE="appv2.entrypoints.migrate"
APPV2_API_APP="appv2.entrypoints.api:app"
APPV2_WORKER_MODULE="appv2.entrypoints.worker"
APPV2_HEALTH_PATH="/api/v2/operations/health"
MONITOR_ROOT="${MONITOR_ROOT:-$ROOT_DIR/books}"
STORAGE_ROOT="${STORAGE_ROOT:-$ROOT_DIR/storage}"
SESSION_SECRET="${SESSION_SECRET:-dev-test-session-secret-change-me-at-least-32-chars}"
DATABASE_URL="${DATABASE_URL:-${APPV2_TEST_DATABASE_URL:-}}"
DATABASE_SOURCE="external PostgreSQL 18.x"
DEV_POSTGRES_IMAGE="${DEV_POSTGRES_IMAGE:-postgres:18.4-alpine3.23}"
DEV_POSTGRES_CONTAINER="${DEV_POSTGRES_CONTAINER:-shuku-appv2-dev-postgres}"
DEV_POSTGRES_VOLUME="${DEV_POSTGRES_VOLUME:-shuku-appv2-dev-postgres-data}"
DEV_POSTGRES_PORT="${DEV_POSTGRES_PORT:-55432}"

case "$MONITOR_ROOT" in
  /*) ;;
  *) MONITOR_ROOT="$ROOT_DIR/$MONITOR_ROOT" ;;
esac
case "$STORAGE_ROOT" in
  /*) ;;
  *) STORAGE_ROOT="$ROOT_DIR/$STORAGE_ROOT" ;;
esac

if [ ! -d "$MONITOR_ROOT" ]; then
  mkdir -p "$MONITOR_ROOT"
fi
mkdir -p "$STORAGE_ROOT/v2/secrets"

if [ -z "$DATABASE_URL" ]; then
  if ! command -v docker >/dev/null 2>&1; then
    echo "Docker is required to start the built-in PostgreSQL 18 development database." >&2
    echo "Alternatively, export DATABASE_URL or APPV2_TEST_DATABASE_URL." >&2
    exit 1
  fi
  if ! docker info >/dev/null 2>&1; then
    echo "Docker is installed but its daemon is not running." >&2
    echo "Start Docker, or export DATABASE_URL for an external PostgreSQL 18.x database." >&2
    exit 1
  fi
  if docker container inspect "$DEV_POSTGRES_CONTAINER" >/dev/null 2>&1; then
    echo "Docker container $DEV_POSTGRES_CONTAINER already exists." >&2
    echo "Stop/remove that development container or export DATABASE_URL explicitly." >&2
    exit 1
  fi

  postgres_password_file="$STORAGE_ROOT/v2/secrets/dev-postgres-password"
  if [ ! -s "$postgres_password_file" ]; then
    if docker volume inspect "$DEV_POSTGRES_VOLUME" >/dev/null 2>&1; then
      echo "Development PostgreSQL volume exists but its password file is missing:" >&2
      echo "  $postgres_password_file" >&2
      echo "Restore the password file or remove volume $DEV_POSTGRES_VOLUME to create a new database." >&2
      exit 1
    fi
    umask 077
    openssl rand -hex 32 > "$postgres_password_file"
  fi
  postgres_password="$(tr -d '\r\n' < "$postgres_password_file")"

  echo "Starting built-in PostgreSQL 18 development database..."
  docker run -d --rm \
    --name "$DEV_POSTGRES_CONTAINER" \
    -e POSTGRES_DB=shuku_v2 \
    -e POSTGRES_USER=shuku \
    -e "POSTGRES_PASSWORD=$postgres_password" \
    -e PGDATA=/var/lib/postgresql/18/docker \
    -p "127.0.0.1:$DEV_POSTGRES_PORT:5432" \
    -v "$DEV_POSTGRES_VOLUME:/var/lib/postgresql" \
    --health-cmd "pg_isready -U shuku -d shuku_v2" \
    --health-interval 2s \
    --health-timeout 3s \
    --health-retries 30 \
    "$DEV_POSTGRES_IMAGE" >/dev/null
  MANAGED_POSTGRES_CONTAINER="$DEV_POSTGRES_CONTAINER"

  i=0
  until [ "$(docker inspect --format '{{.State.Health.Status}}' "$DEV_POSTGRES_CONTAINER" 2>/dev/null || true)" = "healthy" ]; do
    i=$((i + 1))
    if ! docker inspect "$DEV_POSTGRES_CONTAINER" >/dev/null 2>&1; then
      echo "Built-in PostgreSQL container exited before becoming ready." >&2
      exit 1
    fi
    if [ "$i" -ge 60 ]; then
      echo "Built-in PostgreSQL 18 did not become ready in time." >&2
      exit 1
    fi
    sleep 1
  done

  DATABASE_URL="postgresql+psycopg://shuku:$postgres_password@127.0.0.1:$DEV_POSTGRES_PORT/shuku_v2"
  DATABASE_SOURCE="built-in PostgreSQL 18.x on 127.0.0.1:$DEV_POSTGRES_PORT"
fi

ALLOWED_ORIGINS="${ALLOWED_ORIGINS:-[\"http://localhost:$WEB_PORT\",\"http://127.0.0.1:$WEB_PORT\"]}"

export ALLOWED_ORIGINS DATABASE_URL MONITOR_ROOT STORAGE_ROOT SESSION_SECRET WEB_PORT

(
  cd apps/api-python
  uv run python -m "$APPV2_MIGRATE_MODULE"
)

echo "Starting appv2 test service:"
echo "  Web:          http://localhost:$WEB_PORT"
echo "  Web mode:     $WEB_MODE"
echo "  Backend:      $APPV2_API_APP"
echo "  Worker:       $APPV2_WORKER_MODULE"
echo "  Health check: http://localhost:$WEB_PORT$APPV2_HEALTH_PATH"
echo "  Python API:   http://127.0.0.1:$PYTHON_API_PORT"
echo "  Database:     $DATABASE_SOURCE"
echo "  Monitor root: $MONITOR_ROOT"
echo "  Storage root: $STORAGE_ROOT"
if command -v ipconfig >/dev/null 2>&1; then
  LAN_IP="$(ipconfig getifaddr en0 2>/dev/null || true)"
  if [ -n "$LAN_IP" ]; then
    echo "  iOS LAN URL:   http://$LAN_IP:$WEB_PORT/?debug=1"
  fi
fi

(
  cd apps/api-python
  exec env \
  MONITOR_ROOT="$MONITOR_ROOT" \
    STORAGE_ROOT="$STORAGE_ROOT" \
    SESSION_SECRET="$SESSION_SECRET" \
    DATABASE_URL="$DATABASE_URL" \
    uv run --extra dev uvicorn "$APPV2_API_APP" --host 127.0.0.1 --port "$PYTHON_API_PORT"
) &
CHILD_PIDS="$CHILD_PIDS $!"

echo "Waiting for Python API..."
i=0
until node -e "fetch(process.argv[1]).then((r) => process.exit(r.ok ? 0 : 1)).catch(() => process.exit(1))" "http://127.0.0.1:$PYTHON_API_PORT$APPV2_HEALTH_PATH"; do
  i=$((i + 1))
  if [ "$i" -ge 60 ]; then
    echo "Python API did not become ready in time." >&2
    exit 1
  fi
  sleep 1
done

(
  cd apps/api-python
  exec env \
  MONITOR_ROOT="$MONITOR_ROOT" \
    STORAGE_ROOT="$STORAGE_ROOT" \
    SESSION_SECRET="$SESSION_SECRET" \
    DATABASE_URL="$DATABASE_URL" \
    MONITOR_REFRESH_INTERVAL_MS="${MONITOR_REFRESH_INTERVAL_MS:-10000}" \
    uv run --extra dev python -m "$APPV2_WORKER_MODULE"
) &
CHILD_PIDS="$CHILD_PIDS $!"

pnpm --filter @shuku/web exec node scripts/prepare-pdfjs-worker.mjs

if [ "$WEB_MODE" = "start" ]; then
  pnpm --filter @shuku/web exec next start -H "$WEB_HOST" -p "$WEB_PORT" &
else
  pnpm --filter @shuku/web exec next dev -H "$WEB_HOST" -p "$WEB_PORT" &
fi
CHILD_PIDS="$CHILD_PIDS $!"

wait
