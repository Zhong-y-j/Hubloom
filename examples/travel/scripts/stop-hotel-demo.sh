#!/usr/bin/env bash
# 停止 Hubloom + 酒店 mock
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/../../.." && pwd)"
PID_DIR="$ROOT/examples/travel/scripts/.pids"

stop_one() {
  local name="$1"
  local pid_file="$PID_DIR/${name}.pid"
  if [[ ! -f "$pid_file" ]]; then
    return 0
  fi
  local pid
  pid="$(cat "$pid_file")"
  if kill -0 "$pid" 2>/dev/null; then
    echo "停止 ${name} (pid ${pid})"
    kill "$pid" 2>/dev/null || true
    wait "$pid" 2>/dev/null || true
  fi
  rm -f "$pid_file"
}

stop_one hotel
stop_one hubloom

echo "演示服务已停止"
