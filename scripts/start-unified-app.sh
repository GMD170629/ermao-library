#!/bin/sh
set -eu

ROOT_DIR="${ROOT_DIR:-/app}"
PYTHON_API_PORT="8000"
WEB_PORT="${PORT:-3000}"
NEXT_INTERNAL_PORT="${NEXT_INTERNAL_PORT:-3001}"
PYTHON_API_DIR="${PYTHON_API_DIR:-$ROOT_DIR/apps/api-python}"
BUSINESS_PYTHON="${SHUKU_BUSINESS_PYTHON:?fixed launcher must select business Python / 固定入口必须指定业务 Python}"
NEXT_SERVER="${NEXT_SERVER:-$ROOT_DIR/apps/web/server.js}"
GATEWAY_SERVER="${GATEWAY_SERVER:-$ROOT_DIR/scripts/unified-http-gateway.mjs}"

shutdown() {
  trap '' INT TERM
  trap - EXIT
  for group in ${WORKER_PID:-} ${WORKER_RETIRED_GROUP:-}; do
    kill -TERM "-$group" 2>/dev/null || true
  done
  for pid in ${GATEWAY_PID:-} ${PRESTART_PID:-} ${API_PID:-} ${WORKER_PID:-} ${WEB_PID:-}; do
    if [ -n "$pid" ] && kill -0 "$pid" 2>/dev/null; then
      kill "$pid" 2>/dev/null || true
    fi
  done
  wait ${PRESTART_PID:-} ${API_PID:-} ${WORKER_PID:-} ${WEB_PID:-} ${GATEWAY_PID:-} 2>/dev/null || true
}

drain_for_update() {
  # Stop public ingress, notify API background consumers before request draining.
  if [ -n "${GATEWAY_PID:-}" ]; then kill "$GATEWAY_PID" 2>/dev/null || true; fi
  if [ -n "${API_PID:-}" ]; then kill -USR1 "$API_PID" 2>/dev/null || true; fi
  exit 0
}

trap drain_for_update USR1
trap 'exit 130' INT
trap 'exit 143' TERM
trap shutdown EXIT

export STORAGE_ROOT="${STORAGE_ROOT:-$ROOT_DIR/storage}"
mkdir -p "$STORAGE_ROOT/database" "$STORAGE_ROOT/covers" "$STORAGE_ROOT/indexes" "$STORAGE_ROOT/logs" "$STORAGE_ROOT/secrets"

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
  exec "$BUSINESS_PYTHON" -m app.bootstrap.prestart
) &
PRESTART_PID="$!"
wait "$PRESTART_PID"
PRESTART_PID=""

(
  cd "$PYTHON_API_DIR"
  exec "$BUSINESS_PYTHON" -m uvicorn app.main:app --host 127.0.0.1 --port "$PYTHON_API_PORT"
) &
API_PID="$!"

while :; do
  if ! kill -0 "$API_PID" 2>/dev/null; then
    wait "$API_PID" || exit $?
    exit 1
  fi
  if "$BUSINESS_PYTHON" -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:${PYTHON_API_PORT}/api/health', timeout=1).read()" >/dev/null 2>&1; then
    break
  fi
  sleep 1
done

start_worker() {
  if [ -n "${IMPORT_WORKER_READY_FILE:-}" ]; then rm -f "$IMPORT_WORKER_READY_FILE" || echo "update warning / 更新提醒：WORKER_READY_CLEANUP_FAILED" >&2; fi
  (
    cd "$PYTHON_API_DIR"
    exec setsid "$BUSINESS_PYTHON" -m app.worker.main
  ) &
  WORKER_PID="$!"
}
start_worker
WORKER_RESTARTS=0
WORKER_RESTART_AT=0
WORKER_RETIRED_GROUP=""

HOSTNAME=127.0.0.1 PORT="$NEXT_INTERNAL_PORT" node "$NEXT_SERVER" &
WEB_PID="$!"

GATEWAY_HOST="${HOSTNAME:-0.0.0.0}" \
  GATEWAY_PORT="$WEB_PORT" \
  API_PORT="$PYTHON_API_PORT" \
  WEB_UPSTREAM_PORT="$NEXT_INTERNAL_PORT" \
  node "$GATEWAY_SERVER" &
GATEWAY_PID="$!"

while :; do
  for pid in "$API_PID" "$WEB_PID" "$GATEWAY_PID"; do
    if ! kill -0 "$pid" 2>/dev/null; then
      wait "$pid" || exit $?
      exit 1
    fi
  done
  if [ -n "$WORKER_PID" ] && ! kill -0 "$WORKER_PID" 2>/dev/null; then
    worker_exit=0
    wait "$WORKER_PID" || worker_exit=$?
    WORKER_RETIRED_GROUP="$WORKER_PID"
    WORKER_PID=""
    if [ -n "${IMPORT_WORKER_READY_FILE:-}" ]; then rm -f "$IMPORT_WORKER_READY_FILE" || echo "update warning / 更新提醒：WORKER_READY_CLEANUP_FAILED" >&2; fi
    echo "worker.offline exit=$worker_exit restart_count=$WORKER_RESTARTS" >&2
    if [ "$WORKER_RESTARTS" -lt 3 ]; then
      WORKER_RESTART_AT=$(( $(date +%s) + 5 * (1 << WORKER_RESTARTS) ))
    else
      WORKER_RESTART_AT=0
      echo "worker.paused reason=restart_limit" >&2
    fi
  fi
  if [ -z "$WORKER_PID" ] && [ "$WORKER_RESTART_AT" -gt 0 ] && [ "$(date +%s)" -ge "$WORKER_RESTART_AT" ]; then
    # Do not create another consumer while tools from the old worker remain.
    # The fixed launcher reaps adopted children. No files or tasks are reset.
    if kill -0 "-$WORKER_RETIRED_GROUP" 2>/dev/null; then
      WORKER_RESTART_AT=0
      echo "worker.paused reason=previous_execution_still_alive" >&2
    else
      WORKER_RESTARTS=$((WORKER_RESTARTS + 1))
      WORKER_RESTART_AT=0
      start_worker
    fi
  fi
  sleep 2
done
