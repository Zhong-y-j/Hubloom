#!/usr/bin/env bash
# 同时启动景点 mock + Hubloom（景点先启，保证 openapi.json 可拉取）
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/../../.." && pwd)"
cd "$ROOT"

PID_DIR="examples/travel/scripts/.pids"
LOG_DIR="examples/travel/scripts/logs"
mkdir -p "$PID_DIR" "$LOG_DIR"

HUBLOOM_PORT="${HUBLOOM_PORT:-8004}"
ATTRACTION_PORT="${ATTRACTION_PORT:-9004}"
HUBLOOM_URL="http://127.0.0.1:${HUBLOOM_PORT}"
ATTRACTION_URL="http://127.0.0.1:${ATTRACTION_PORT}"

pids_on_port() {
  lsof -tiTCP:"$1" -sTCP:LISTEN 2>/dev/null | sort -u | tr '\n' ' ' | sed 's/[[:space:]]*$//' || true
}

record_listener_pid() {
  local port="$1"
  local pid_file="$2"
  local pid
  pid="$(pids_on_port "$port" | awk '{print $1}')"
  if [[ -n "$pid" ]]; then
    echo "$pid" >"$pid_file"
    return 0
  fi
  return 1
}

is_service_running() {
  local pid_file="$1"
  local port="$2"
  [[ -f "$pid_file" ]] && kill -0 "$(cat "$pid_file")" 2>/dev/null && [[ -n "$(pids_on_port "$port")" ]]
}

if is_service_running "$PID_DIR/attraction.pid" "$ATTRACTION_PORT"; then
  echo "景点服务已在运行 (pid $(cat "$PID_DIR/attraction.pid"))"
else
  stale_pids="$(pids_on_port "$ATTRACTION_PORT")"
  if [[ -n "$stale_pids" ]]; then
    echo "清理占用 ${ATTRACTION_PORT} 的旧景点进程 (pid ${stale_pids})"
    # shellcheck disable=SC2086
    kill $stale_pids 2>/dev/null || true
    sleep 1
  fi
  rm -f "$PID_DIR/attraction.pid"
  echo "启动景点 mock → ${ATTRACTION_URL}"
  HUBLOOM_BASE_URL="$HUBLOOM_URL" \
  ATTRACTION_PUBLIC_URL="$ATTRACTION_URL" \
  PYTHONPATH=. \
  uv run python -m examples.travel.mocks.attraction \
    >"$LOG_DIR/attraction.log" 2>&1 &
  for _ in $(seq 1 20); do
    if record_listener_pid "$ATTRACTION_PORT" "$PID_DIR/attraction.pid"; then
      break
    fi
    sleep 1
  done
fi

echo "等待景点服务就绪…"
for _ in $(seq 1 20); do
  if curl -sf "${ATTRACTION_URL}/health" >/dev/null 2>&1; then
    break
  fi
  sleep 1
done

if is_service_running "$PID_DIR/hubloom-attraction.pid" "$HUBLOOM_PORT"; then
  echo "Hubloom 已在运行 (pid $(cat "$PID_DIR/hubloom-attraction.pid"))"
else
  stale_pids="$(pids_on_port "$HUBLOOM_PORT")"
  if [[ -n "$stale_pids" ]]; then
    echo "清理占用 ${HUBLOOM_PORT} 的旧 Hubloom 进程 (pid ${stale_pids})"
    # shellcheck disable=SC2086
    kill $stale_pids 2>/dev/null || true
    sleep 1
  fi
  rm -f "$PID_DIR/hubloom-attraction.pid"
  echo "启动 Hubloom → ${HUBLOOM_URL}"
  CORTEX_API_PORT="$HUBLOOM_PORT" \
  CORTEX_MEMORY_DB=data/memory-attraction.db \
  PYTHONPATH=. \
  uv run python -m agents.api.app \
    >"$LOG_DIR/hubloom-attraction.log" 2>&1 &
  for _ in $(seq 1 30); do
    if record_listener_pid "$HUBLOOM_PORT" "$PID_DIR/hubloom-attraction.pid"; then
      break
    fi
    sleep 1
  done
fi

echo "等待 Hubloom 就绪…"
for _ in $(seq 1 30); do
  if curl -sf "${HUBLOOM_URL}/health" >/dev/null 2>&1; then
    break
  fi
  sleep 1
done

echo "向 Hubloom 注册景点 OpenAPI…"
if curl -sf -X POST "${HUBLOOM_URL}/v1/config/apply" \
  -H "Content-Type: application/json" \
  -d "{\"mcp_swagger_url\":\"${ATTRACTION_URL}/openapi.json\",\"mcp_base_url\":\"${ATTRACTION_URL}\",\"mcp_auth_scheme\":\"Bearer\"}" \
  >/dev/null; then
  echo "景点 API 已加载到 Hubloom"
else
  echo "注册未完成（Hubloom 未就绪或 openapi 不可达），打开聊天页时会自动重试"
fi

echo ""
echo "已启动："
echo "  景点登录页       ${ATTRACTION_URL}/login"
echo "  景点聊天页       ${ATTRACTION_URL}/chat"
echo "  Hubloom（编排）  ${HUBLOOM_URL}"
echo ""
echo "日志："
echo "  $LOG_DIR/attraction.log"
echo "  $LOG_DIR/hubloom-attraction.log"
echo ""
echo "停止：./examples/travel/scripts/stop-attraction-demo.sh"
