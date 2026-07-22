#!/bin/bash
set -eu

port="${wizard_port:-}"

case "$port" in
  ''|*[!0-9]*)
    echo "Web 访问端口必须是 1024-65535 之间的整数。" > "${TRIM_TEMP_LOGFILE:-/dev/stderr}"
    exit 1
    ;;
esac

if [ "$port" -lt 1024 ] || [ "$port" -gt 65535 ]; then
  echo "Web 访问端口必须是 1024-65535 之间的整数。" > "${TRIM_TEMP_LOGFILE:-/dev/stderr}"
  exit 1
fi
