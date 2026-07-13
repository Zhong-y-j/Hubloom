#!/usr/bin/env bash
# 停止景点 mock + Hubloom
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/../../.." && pwd)"
PID_DIR="$ROOT/examples/travel/scripts/.pids"
HUBLOOM_PORT="${HUBLOOM_PORT:-8004}"
ATTRACTION_PORT="${ATTRACTION_PORT:-9004}"

pids_on_port() {
  lsof -tiTCP:"$1" -sTCP:LISTEN 2>/dev/null | sort -u | tr '\n' ' ' | sed 's/[[:space:]]*$//' || true
}

stop_one() {
  local name="$1"
  local port="$2"
  local pid_file="$PID_DIR/${name}.pid"
  local stopped=0

  if [[ -f "$pid_file" ]]; then
    local pid
    pid="$(cat "$pid_file")"
    if kill -0 "$pid" 2>/dev/null; then
      echo "停止 ${name} (pid ${pid})"
      pkill -P "$pid" 2>/dev/null || true
      kill "$pid" 2>/dev/null || true
      wait "$pid" 2>/dev/null || true
      stopped=1
    fi
    rm -f "$pid_file"
  fi

  local port_pids
  port_pids="$(pids_on_port "$port")"
  if [[ -n "$port_pids" ]]; then
    echo "停止 ${name} (port ${port}, pid ${port_pids})"
    # shellcheck disable=SC2086
    kill $port_pids 2>/dev/null || true
    stopped=1
  fi

  if [[ "$stopped" -eq 0 ]]; then
    echo "${name} 未在运行"
  fi
}

stop_one attraction "$ATTRACTION_PORT"
stop_one hubloom-attraction "$HUBLOOM_PORT"

echo "演示服务已停止"
