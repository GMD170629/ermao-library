#!/bin/sh
set -eu

ROOT_DIR="${ROOT_DIR:-/app}"
PYTHON_API_PORT="8000"
WEB_PORT="${PORT:-3000}"
NEXT_INTERNAL_PORT="${NEXT_INTERNAL_PORT:-3001}"
PYTHON_API_DIR="${PYTHON_API_DIR:-$ROOT_DIR/apps/api-python}"
NEXT_SERVER="${NEXT_SERVER:-$ROOT_DIR/apps/web/server.js}"
GATEWAY_SERVER="${GATEWAY_SERVER:-$ROOT_DIR/scripts/unified-http-gateway.mjs}"

shutdown() {
  trap - INT TERM EXIT
  for pid in ${API_PID:-} ${WORKER_PID:-} ${WEB_PID:-} ${GATEWAY_PID:-}; do
    if [ -n "$pid" ] && kill -0 "$pid" 2>/dev/null; then
      kill "$pid" 2>/dev/null || true
    fi
  done
  wait ${API_PID:-} ${WORKER_PID:-} ${WEB_PID:-} ${GATEWAY_PID:-} 2>/dev/null || true
}

trap shutdown INT TERM EXIT

export STORAGE_ROOT="${STORAGE_ROOT:-$ROOT_DIR/storage}"
mkdir -p "$STORAGE_ROOT/database" "$STORAGE_ROOT/covers" "$STORAGE_ROOT/indexes" "$STORAGE_ROOT/conversions" "$STORAGE_ROOT/temp/conversions" "$STORAGE_ROOT/logs" "$STORAGE_ROOT/secrets"

if [ -z "${SESSION_SECRET:-}" ]; then
  secret_file="$STORAGE_ROOT/secrets/session-secret"
  if [ ! -s "$secret_file" ]; then
    umask 077
    if command -v openssl >/dev/null 2>&1; then
      openssl rand -hex 32 > "$secret_file"
    else
      node -e "process.stdout.write(require('node:crypto').randomBytes(32).toString('hex'))" > "$secret_file"
    fi
  fi
  SESSION_SECRET="$(tr -d '\r\n' < "$secret_file")"
  export SESSION_SECRET
fi

(
  cd "$PYTHON_API_DIR"
  uvicorn app.main:app --host 127.0.0.1 --port "$PYTHON_API_PORT"
) &
API_PID="$!"

api_ready=0
attempt=0
while [ "$attempt" -lt 60 ]; do
  if ! kill -0 "$API_PID" 2>/dev/null; then
    wait "$API_PID" || exit $?
    exit 1
  fi
  if python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:${PYTHON_API_PORT}/api/health', timeout=1).read()" >/dev/null 2>&1; then
    api_ready=1
    break
  fi
  attempt=$((attempt + 1))
  sleep 1
done

if [ "$api_ready" -ne 1 ]; then
  echo "Python API did not become ready within 60 seconds" >&2
  exit 1
fi

(
  cd "$PYTHON_API_DIR"
  python -m app.worker.main
) &
WORKER_PID="$!"

HOSTNAME=127.0.0.1 PORT="$NEXT_INTERNAL_PORT" node "$NEXT_SERVER" &
WEB_PID="$!"

GATEWAY_HOST="${HOSTNAME:-0.0.0.0}" \
  GATEWAY_PORT="$WEB_PORT" \
  API_PORT="$PYTHON_API_PORT" \
  WEB_UPSTREAM_PORT="$NEXT_INTERNAL_PORT" \
  node "$GATEWAY_SERVER" &
GATEWAY_PID="$!"

while :; do
  for pid in "$API_PID" "$WORKER_PID" "$WEB_PID" "$GATEWAY_PID"; do
    if ! kill -0 "$pid" 2>/dev/null; then
      wait "$pid" || exit $?
      exit 1
    fi
  done
  sleep 2
done
