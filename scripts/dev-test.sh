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
MOBI_CORE_BUILD_DIR="${MOBI_CORE_BUILD_DIR:-$ROOT_DIR/build/mobi-core-runtime}"

run_cmake() {
  if command -v cmake >/dev/null 2>&1; then
    cmake "$@"
    return
  fi
  if command -v uv >/dev/null 2>&1; then
    uvx --from cmake cmake "$@"
    return
  fi
  echo "CMake is required to build the pinned libmobi runtime." >&2
  exit 1
}

find_host_compiler() {
  override="$1"
  shift

  if [ -n "$override" ]; then
    if command -v "$override" >/dev/null 2>&1; then
      command -v "$override"
      return
    fi
    echo "Configured MOBI host compiler is not executable: $override" >&2
    exit 1
  fi

  for compiler in "$@"; do
    if command -v "$compiler" >/dev/null 2>&1; then
      command -v "$compiler"
      return
    fi
  done

  echo "A host C/C++ toolchain is required to build the pinned libmobi runtime." >&2
  echo "On Ubuntu/Debian, install it with: sudo apt-get install build-essential" >&2
  exit 1
}

find_built_mobi_core_library() {
  host_system="$(uname -s 2>/dev/null || true)"

  case "$host_system" in
    Darwin)
      set -- \
        "$MOBI_CORE_BUILD_DIR/libermao_mobi_core.dylib" \
        "$MOBI_CORE_BUILD_DIR/Release/libermao_mobi_core.dylib"
      ;;
    Linux)
      set -- \
        "$MOBI_CORE_BUILD_DIR/libermao_mobi_core.so" \
        "$MOBI_CORE_BUILD_DIR/Release/libermao_mobi_core.so"
      ;;
    CYGWIN* | MINGW* | MSYS*)
      set -- \
        "$MOBI_CORE_BUILD_DIR/ermao_mobi_core.dll" \
        "$MOBI_CORE_BUILD_DIR/libermao_mobi_core.dll" \
        "$MOBI_CORE_BUILD_DIR/Release/ermao_mobi_core.dll" \
        "$MOBI_CORE_BUILD_DIR/Release/libermao_mobi_core.dll"
      ;;
    *)
      set -- \
        "$MOBI_CORE_BUILD_DIR/libermao_mobi_core.so" \
        "$MOBI_CORE_BUILD_DIR/libermao_mobi_core.dylib" \
        "$MOBI_CORE_BUILD_DIR/ermao_mobi_core.dll" \
        "$MOBI_CORE_BUILD_DIR/libermao_mobi_core.dll" \
        "$MOBI_CORE_BUILD_DIR/Release/libermao_mobi_core.so" \
        "$MOBI_CORE_BUILD_DIR/Release/libermao_mobi_core.dylib" \
        "$MOBI_CORE_BUILD_DIR/Release/ermao_mobi_core.dll" \
        "$MOBI_CORE_BUILD_DIR/Release/libermao_mobi_core.dll"
      ;;
  esac

  for library_path in "$@"; do
    if [ -f "$library_path" ]; then
      printf '%s\n' "$library_path"
      return 0
    fi
  done

  return 1
}

case "$STORAGE_ROOT" in
  /*) ;;
  *) STORAGE_ROOT="$ROOT_DIR/$STORAGE_ROOT" ;;
esac

mkdir -p "$STORAGE_ROOT/database"
DATABASE_PATH="$STORAGE_ROOT/database/shuku.sqlite3"

if [ -z "${ERMAO_MOBI_CORE_LIBRARY:-}" ]; then
  # Select the host toolchain explicitly. CMake build directories are persistent,
  # and may otherwise retain an Android or PDFium compiler from another workflow.
  MOBI_CORE_C_COMPILER="$(
    find_host_compiler "${MOBI_CORE_C_COMPILER:-}" cc gcc clang
  )"
  MOBI_CORE_CXX_COMPILER="$(
    find_host_compiler "${MOBI_CORE_CXX_COMPILER:-}" c++ g++ clang++
  )"
  run_cmake \
    -S "$ROOT_DIR/apps/mobile/native/mobi-core" \
    -B "$MOBI_CORE_BUILD_DIR" \
    -DCMAKE_C_COMPILER="$MOBI_CORE_C_COMPILER" \
    -DCMAKE_CXX_COMPILER="$MOBI_CORE_CXX_COMPILER" \
    -DERMAO_MOBI_BUILD_TESTS=OFF \
    -DERMAO_MOBI_BUILD_FUZZER=OFF
  run_cmake \
    --build "$MOBI_CORE_BUILD_DIR" \
    --config Release \
    --target ermao_mobi_core_shared
  if ! ERMAO_MOBI_CORE_LIBRARY="$(find_built_mobi_core_library)"; then
    echo "Pinned libmobi runtime is unavailable under: $MOBI_CORE_BUILD_DIR" >&2
    exit 1
  fi
fi

if [ ! -f "$ERMAO_MOBI_CORE_LIBRARY" ]; then
  echo "Pinned libmobi runtime is unavailable: $ERMAO_MOBI_CORE_LIBRARY" >&2
  exit 1
fi

export STORAGE_ROOT SESSION_SECRET WEB_PORT ERMAO_MOBI_CORE_LIBRARY

(
  cd apps/api-python
  uv run python -m app.bootstrap.prestart
)

echo "Starting test service:"
echo "  Web:          http://localhost:$WEB_PORT"
echo "  Web mode:     $WEB_MODE"
echo "  Health check: http://localhost:$WEB_PORT/api/health"
echo "  Python API:   http://127.0.0.1:$PYTHON_API_PORT"
echo "  Database:     $DATABASE_PATH"
echo "  Storage root: $STORAGE_ROOT"
echo "  MOBI runtime: $ERMAO_MOBI_CORE_LIBRARY"
LAN_INTERFACE="$(route -n get default 2>/dev/null | awk '/interface:/{print $2; exit}' || true)"
LAN_IP=""
if [ -n "$LAN_INTERFACE" ] && command -v ipconfig >/dev/null 2>&1; then
  LAN_IP="$(ipconfig getifaddr "$LAN_INTERFACE" 2>/dev/null || true)"
fi
if [ -z "$LAN_IP" ] && [ -n "$LAN_INTERFACE" ] && command -v ifconfig >/dev/null 2>&1; then
  LAN_IP="$(ifconfig "$LAN_INTERFACE" 2>/dev/null | awk '/inet /{print $2; exit}' || true)"
fi
if [ -n "$LAN_IP" ]; then
  echo "  LAN URL:       http://$LAN_IP:$WEB_PORT/?debug=1"
fi

(
  cd apps/api-python
  exec env \
    STORAGE_ROOT="$STORAGE_ROOT" \
    SESSION_SECRET="$SESSION_SECRET" \
    ERMAO_MOBI_CORE_LIBRARY="$ERMAO_MOBI_CORE_LIBRARY" \
    uv run --extra dev uvicorn app.main:app --host 127.0.0.1 --port "$PYTHON_API_PORT"
) &
PYTHON_API_PID="$!"
CHILD_PIDS="$CHILD_PIDS $PYTHON_API_PID"

echo "Waiting for Python API..."
while :; do
  if ! kill -0 "$PYTHON_API_PID" 2>/dev/null; then
    wait "$PYTHON_API_PID" || exit $?
    exit 1
  fi
  if node -e "fetch(process.argv[1]).then((r) => process.exit(r.ok ? 0 : 1)).catch(() => process.exit(1))" "http://127.0.0.1:$PYTHON_API_PORT/api/health"; then
    break
  fi
  sleep 1
done

(
  cd apps/api-python
  exec env \
    STORAGE_ROOT="$STORAGE_ROOT" \
    SESSION_SECRET="$SESSION_SECRET" \
    ERMAO_MOBI_CORE_LIBRARY="$ERMAO_MOBI_CORE_LIBRARY" \
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
