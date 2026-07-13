#!/usr/bin/env bash
# 同时启动酒店 mock + Hubloom（酒店先启，保证 openapi.json 可拉取）
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/../../.." && pwd)"
cd "$ROOT"

PID_DIR="examples/travel/scripts/.pids"
LOG_DIR="examples/travel/scripts/logs"
mkdir -p "$PID_DIR" "$LOG_DIR"

HUBLOOM_PORT="${HUBLOOM_PORT:-8001}"
HOTEL_PORT="${HOTEL_PORT:-9001}"
HUBLOOM_URL="http://127.0.0.1:${HUBLOOM_PORT}"
HOTEL_URL="http://127.0.0.1:${HOTEL_PORT}"

if [[ -f "$PID_DIR/hotel.pid" ]] && kill -0 "$(cat "$PID_DIR/hotel.pid")" 2>/dev/null; then
  echo "酒店服务已在运行 (pid $(cat "$PID_DIR/hotel.pid"))"
else
  echo "启动酒店 mock → ${HOTEL_URL}"
  HUBLOOM_BASE_URL="$HUBLOOM_URL" \
  HOTEL_PUBLIC_URL="$HOTEL_URL" \
  PYTHONPATH=. \
  uv run python -m examples.travel.mocks.hotel \
    >"$LOG_DIR/hotel.log" 2>&1 &
  echo $! >"$PID_DIR/hotel.pid"
fi

echo "等待酒店服务就绪…"
for _ in $(seq 1 20); do
  if curl -sf "${HOTEL_URL}/health" >/dev/null 2>&1; then
    break
  fi
  sleep 1
done

if [[ -f "$PID_DIR/hubloom.pid" ]] && kill -0 "$(cat "$PID_DIR/hubloom.pid")" 2>/dev/null; then
  echo "Hubloom 已在运行 (pid $(cat "$PID_DIR/hubloom.pid"))"
else
  echo "启动 Hubloom → ${HUBLOOM_URL}"
  CORTEX_API_PORT="$HUBLOOM_PORT" \
  CORTEX_MEMORY_DB=data/memory-hotel.db \
  PYTHONPATH=. \
  uv run python -m agents.api.app \
    >"$LOG_DIR/hubloom.log" 2>&1 &
  echo $! >"$PID_DIR/hubloom.pid"
fi

echo "等待 Hubloom 就绪…"
for _ in $(seq 1 30); do
  if curl -sf "${HUBLOOM_URL}/health" >/dev/null 2>&1; then
    break
  fi
  sleep 1
done

echo "向 Hubloom 注册酒店 OpenAPI…"
if curl -sf -X POST "${HUBLOOM_URL}/v1/config/apply" \
  -H "Content-Type: application/json" \
  -d "{\"mcp_swagger_url\":\"${HOTEL_URL}/openapi.json\",\"mcp_base_url\":\"${HOTEL_URL}\",\"mcp_auth_scheme\":\"Bearer\"}" \
  >/dev/null; then
  echo "酒店 API 已加载到 Hubloom"
else
  echo "注册未完成（Hubloom 未就绪或 openapi 不可达），打开聊天页时会自动重试"
fi

echo ""
echo "已启动："
echo "  酒店登录页       ${HOTEL_URL}/login"
echo "  酒店聊天页       ${HOTEL_URL}/chat"
echo "  Hubloom（编排）  ${HUBLOOM_URL}"
echo ""
echo "日志："
echo "  $LOG_DIR/hotel.log"
echo "  $LOG_DIR/hubloom.log"
echo ""
echo "停止：./examples/travel/scripts/stop-hotel-demo.sh"
