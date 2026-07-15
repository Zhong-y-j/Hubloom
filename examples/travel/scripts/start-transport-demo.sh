#!/usr/bin/env bash
# 同时启动交通 mock + Hubloom（交通先启，保证 openapi.json 可拉取）
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/../../.." && pwd)"
cd "$ROOT"

PID_DIR="examples/travel/scripts/.pids"
LOG_DIR="examples/travel/scripts/logs"
mkdir -p "$PID_DIR" "$LOG_DIR"

HUBLOOM_PORT="${HUBLOOM_PORT:-8003}"
TRANSPORT_PORT="${TRANSPORT_PORT:-9003}"
HOTEL_HUBLOOM_PORT="${HOTEL_HUBLOOM_PORT:-8001}"
ATTRACTION_HUBLOOM_PORT="${ATTRACTION_HUBLOOM_PORT:-8004}"
HUBLOOM_URL="http://127.0.0.1:${HUBLOOM_PORT}"
TRANSPORT_URL="http://127.0.0.1:${TRANSPORT_PORT}"
HOTEL_HUBLOOM_URL="http://127.0.0.1:${HOTEL_HUBLOOM_PORT}"
ATTRACTION_HUBLOOM_URL="http://127.0.0.1:${ATTRACTION_HUBLOOM_PORT}"
# 交通 Hubloom 可经 A2A 委托酒店 / 景点 Agent（三系统互连）
if [[ -z "${A2A_REMOTE_AGENTS:-}" ]]; then
  A2A_REMOTE_AGENTS="[{\"id\":\"travel-hotel\",\"name\":\"酒店助手\",\"url\":\"${HOTEL_HUBLOOM_URL}\"},{\"id\":\"travel-attraction\",\"name\":\"景点助手\",\"url\":\"${ATTRACTION_HUBLOOM_URL}\"}]"
fi

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

if is_service_running "$PID_DIR/transport.pid" "$TRANSPORT_PORT"; then
  echo "交通服务已在运行 (pid $(cat "$PID_DIR/transport.pid"))"
else
  stale_pids="$(pids_on_port "$TRANSPORT_PORT")"
  if [[ -n "$stale_pids" ]]; then
    echo "清理占用 ${TRANSPORT_PORT} 的旧交通进程 (pid ${stale_pids})"
    # shellcheck disable=SC2086
    kill $stale_pids 2>/dev/null || true
    sleep 1
  fi
  rm -f "$PID_DIR/transport.pid"
  echo "启动交通 mock → ${TRANSPORT_URL}"
  HUBLOOM_BASE_URL="$HUBLOOM_URL" \
  TRANSPORT_PUBLIC_URL="$TRANSPORT_URL" \
  PYTHONPATH=. \
  uv run python -m examples.travel.mocks.transport \
    >"$LOG_DIR/transport.log" 2>&1 &
  for _ in $(seq 1 20); do
    if record_listener_pid "$TRANSPORT_PORT" "$PID_DIR/transport.pid"; then
      break
    fi
    sleep 1
  done
fi

echo "等待交通服务就绪…"
for _ in $(seq 1 20); do
  if curl -sf "${TRANSPORT_URL}/health" >/dev/null 2>&1; then
    break
  fi
  sleep 1
done

if is_service_running "$PID_DIR/hubloom-transport.pid" "$HUBLOOM_PORT"; then
  echo "Hubloom 已在运行 (pid $(cat "$PID_DIR/hubloom-transport.pid"))"
else
  stale_pids="$(pids_on_port "$HUBLOOM_PORT")"
  if [[ -n "$stale_pids" ]]; then
    echo "清理占用 ${HUBLOOM_PORT} 的旧 Hubloom 进程 (pid ${stale_pids})"
    # shellcheck disable=SC2086
    kill $stale_pids 2>/dev/null || true
    sleep 1
  fi
  rm -f "$PID_DIR/hubloom-transport.pid"
  echo "启动 Hubloom → ${HUBLOOM_URL}"
  CORTEX_API_PORT="$HUBLOOM_PORT" \
  CORTEX_PUBLIC_URL="$HUBLOOM_URL" \
  CORTEX_MEMORY_DB=data/memory-transport.db \
  A2A_REMOTE_AGENTS="$A2A_REMOTE_AGENTS" \
  PYTHONPATH=. \
  uv run python -m agents.api.app \
    >"$LOG_DIR/hubloom-transport.log" 2>&1 &
  for _ in $(seq 1 30); do
    if record_listener_pid "$HUBLOOM_PORT" "$PID_DIR/hubloom-transport.pid"; then
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

echo "向 Hubloom 注册交通 OpenAPI…"
if curl -sf -X POST "${HUBLOOM_URL}/v1/config/apply" \
  -H "Content-Type: application/json" \
  -d "{\"mcp_swagger_url\":\"${TRANSPORT_URL}/openapi.json\",\"mcp_base_url\":\"${TRANSPORT_URL}\",\"mcp_auth_scheme\":\"Bearer\"}" \
  >/dev/null; then
  echo "交通 API 已加载到 Hubloom"
else
  echo "注册未完成（Hubloom 未就绪或 openapi 不可达），打开聊天页时会自动重试"
fi

echo ""
echo "已启动："
echo "  交通登录页       ${TRANSPORT_URL}/login"
echo "  交通聊天页       ${TRANSPORT_URL}/chat"
echo "  Hubloom（编排）  ${HUBLOOM_URL}"
echo "  Agent Card       ${HUBLOOM_URL}/.well-known/agent-card.json"
echo "  A2A 出站         travel-hotel → ${HOTEL_HUBLOOM_URL}"
echo "                   travel-attraction → ${ATTRACTION_HUBLOOM_URL}"
echo "  （跨系统委托需酒店 / 景点 Hubloom 已启动）"
echo ""
echo "日志："
echo "  $LOG_DIR/transport.log"
echo "  $LOG_DIR/hubloom-transport.log"
echo ""
echo "停止：./examples/travel/scripts/stop-transport-demo.sh"
