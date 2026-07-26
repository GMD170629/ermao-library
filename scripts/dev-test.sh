#!/bin/sh
set -eu

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT_DIR"

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
}
trap cleanup INT TERM EXIT
CHILD_PIDS=""

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

if [ -z "$DATABASE_URL" ]; then
  echo "DATABASE_URL or APPV2_TEST_DATABASE_URL is required and must point to PostgreSQL 18.x." >&2
  echo "Use docker compose for the built-in database, or export an external PostgreSQL URL." >&2
  exit 1
fi

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
mkdir -p "$STORAGE_ROOT/v2"

export DATABASE_URL MONITOR_ROOT STORAGE_ROOT SESSION_SECRET WEB_PORT

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
echo "  Database:     PostgreSQL 18.x from DATABASE_URL"
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
