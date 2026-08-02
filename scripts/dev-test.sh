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
NEXT_INTERNAL_PORT="${NEXT_INTERNAL_PORT:-3001}"
WEB_MODE="${WEB_MODE:-dev}"
STORAGE_ROOT="${STORAGE_ROOT:-$ROOT_DIR/storage}"
SESSION_SECRET="${SESSION_SECRET:-dev-test-session-secret-change-me-at-least-32-chars}"

case "$STORAGE_ROOT" in
  /*) ;;
  *) STORAGE_ROOT="$ROOT_DIR/$STORAGE_ROOT" ;;
esac

mkdir -p "$STORAGE_ROOT/database"
DATABASE_PATH="$STORAGE_ROOT/database/shuku.sqlite3"

export STORAGE_ROOT SESSION_SECRET WEB_PORT

(
  cd apps/api-python
  uv run python -m app.db.bootstrap
)

echo "Starting test service:"
echo "  Web:          http://localhost:$WEB_PORT"
echo "  Web mode:     $WEB_MODE"
echo "  Health check: http://localhost:$WEB_PORT/api/health"
echo "  Python API:   http://127.0.0.1:$PYTHON_API_PORT"
echo "  Database:     $DATABASE_PATH"
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
    STORAGE_ROOT="$STORAGE_ROOT" \
    SESSION_SECRET="$SESSION_SECRET" \
    uv run --extra dev uvicorn app.main:app --host 127.0.0.1 --port "$PYTHON_API_PORT"
) &
CHILD_PIDS="$CHILD_PIDS $!"

echo "Waiting for Python API..."
i=0
until node -e "fetch(process.argv[1]).then((r) => process.exit(r.ok ? 0 : 1)).catch(() => process.exit(1))" "http://127.0.0.1:$PYTHON_API_PORT/api/health"; do
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
    STORAGE_ROOT="$STORAGE_ROOT" \
    SESSION_SECRET="$SESSION_SECRET" \
    MONITOR_REFRESH_INTERVAL_MS="${MONITOR_REFRESH_INTERVAL_MS:-10000}" \
    uv run --extra dev python -m app.worker.main
) &
CHILD_PIDS="$CHILD_PIDS $!"

pnpm --filter @shuku/web exec node scripts/prepare-pdfjs-worker.mjs

if [ "$WEB_MODE" = "start" ]; then
  pnpm --filter @shuku/web exec next start -H 127.0.0.1 -p "$NEXT_INTERNAL_PORT" &
else
  pnpm --filter @shuku/web exec next dev --webpack -H 127.0.0.1 -p "$NEXT_INTERNAL_PORT" &
fi
CHILD_PIDS="$CHILD_PIDS $!"

GATEWAY_HOST="$WEB_HOST" \
  GATEWAY_PORT="$WEB_PORT" \
  API_PORT="$PYTHON_API_PORT" \
  WEB_UPSTREAM_PORT="$NEXT_INTERNAL_PORT" \
  node scripts/unified-http-gateway.mjs &
CHILD_PIDS="$CHILD_PIDS $!"

echo "Waiting for Web gateway..."
i=0
until node -e "fetch(process.argv[1], { redirect: 'manual' }).then((r) => process.exit(r.status < 500 ? 0 : 1)).catch(() => process.exit(1))" "http://127.0.0.1:$WEB_PORT/"; do
  i=$((i + 1))
  if [ "$i" -ge 60 ]; then
    echo "Web gateway did not become ready in time." >&2
    exit 1
  fi
  sleep 1
done

echo "Test service is ready at http://localhost:$WEB_PORT"
echo "Press Ctrl+C to stop the API, import worker, Web server, and gateway."

wait
