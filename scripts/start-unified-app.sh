#!/bin/sh
set -eu

ROOT_DIR="${ROOT_DIR:-/app}"
PYTHON_API_PORT="8000"
WEB_PORT="${PORT:-3000}"
PYTHON_API_DIR="${PYTHON_API_DIR:-$ROOT_DIR/apps/api-python}"
NEXT_SERVER="${NEXT_SERVER:-$ROOT_DIR/apps/web/server.js}"
CONTROL_ROOT="${STORAGE_ROOT:-$ROOT_DIR/storage}/v2/control"

stop_backend() {
  for pid in ${API_PID:-} ${WORKER_PID:-}; do
    if [ -n "$pid" ] && kill -0 "$pid" 2>/dev/null; then
      kill "$pid" 2>/dev/null || true
    fi
  done
  wait ${API_PID:-} ${WORKER_PID:-} 2>/dev/null || true
  API_PID=
  WORKER_PID=
}

shutdown() {
  trap - INT TERM EXIT
  stop_backend
  if [ -n "${WEB_PID:-}" ] && kill -0 "$WEB_PID" 2>/dev/null; then
    kill "$WEB_PID" 2>/dev/null || true
  fi
  wait ${WEB_PID:-} 2>/dev/null || true
}

wait_for_api() {
  attempt=0
  while [ "$attempt" -lt 60 ]; do
    if ! kill -0 "$API_PID" 2>/dev/null; then
      wait "$API_PID" || exit $?
      exit 1
    fi
    if python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:${PYTHON_API_PORT}/api/v2/operations/health', timeout=1).read()" >/dev/null 2>&1; then
      return 0
    fi
    attempt=$((attempt + 1))
    sleep 1
  done
  echo "appv2 API did not become ready within 60 seconds" >&2
  return 1
}

run_migrations() {
  attempt=0
  while [ "$attempt" -lt 60 ]; do
    if (
      cd "$PYTHON_API_DIR"
      python -m appv2.entrypoints.migrate
    ); then
      return 0
    fi
    attempt=$((attempt + 1))
    sleep 2
  done
  echo "appv2 migrations could not reach a PostgreSQL 18 database" >&2
  return 1
}

start_backend() {
  run_migrations
  (
    cd "$PYTHON_API_DIR"
    exec uvicorn appv2.entrypoints.api:app \
      --host 127.0.0.1 \
      --port "$PYTHON_API_PORT"
  ) &
  API_PID="$!"
  wait_for_api

  (
    cd "$PYTHON_API_DIR"
    exec python -m appv2.entrypoints.worker
  ) &
  WORKER_PID="$!"
}

trap shutdown INT TERM EXIT

: "${DATABASE_URL:?DATABASE_URL is required for the appv2 PostgreSQL runtime}"
export STORAGE_ROOT="${STORAGE_ROOT:-$ROOT_DIR/storage}"
export MONITOR_ROOT="${MONITOR_ROOT:-/monitor}"
mkdir -p \
  "$MONITOR_ROOT" \
  "$STORAGE_ROOT/v2/covers" \
  "$STORAGE_ROOT/v2/conversions" \
  "$STORAGE_ROOT/v2/temp" \
  "$STORAGE_ROOT/v2/backups" \
  "$STORAGE_ROOT/v2/control" \
  "$STORAGE_ROOT/v2/logs" \
  "$STORAGE_ROOT/v2/secrets"

if [ -z "${SESSION_SECRET:-}" ]; then
  secret_file="$STORAGE_ROOT/v2/secrets/session-secret"
  if [ ! -s "$secret_file" ]; then
    umask 077
    openssl rand -hex 32 > "$secret_file"
  fi
  SESSION_SECRET="$(tr -d '\r\n' < "$secret_file")"
  export SESSION_SECRET
fi

export HOSTNAME="${HOSTNAME:-0.0.0.0}"
export PORT="$WEB_PORT"

start_backend
node "$NEXT_SERVER" &
WEB_PID="$!"

while :; do
  if ! kill -0 "$WEB_PID" 2>/dev/null; then
    wait "$WEB_PID" || exit $?
    exit 1
  fi
  if ! kill -0 "$API_PID" 2>/dev/null || ! kill -0 "$WORKER_PID" 2>/dev/null; then
    stop_backend
    exit 1
  fi
  restore_request="$(find "$CONTROL_ROOT" -maxdepth 1 -type f -name 'restore-*.request.json' -print -quit)"
  if [ -n "$restore_request" ]; then
    stop_backend
    if ! (
      cd "$PYTHON_API_DIR"
      python -m appv2.entrypoints.restore
    ); then
      echo "appv2 restore failed; restarting API and worker so the result can be inspected" >&2
    fi
    start_backend
  fi
  sleep 2
done
