#!/usr/bin/env bash
# 向 Hubloom 推送 locker.created 事件（业务 Webhook 模拟）。
#
# 幂等键是 event_id（不是 session_id）。重复同一 event_id 会直接返回上次结果。
#
# 用法（仓库根或任意目录）：
#   export HUBLOOM_BEARER_TOKEN='你的业务 Token'
#   ./examples/chat/scripts/post_locker_created.sh
#
# 可选环境变量：
#   HUBLOOM_BASE_URL      默认 http://127.0.0.1:8010
#   HUBLOOM_EVENT_SECRET  默认 change-me（须与 config events.shared_secret 一致）
#   HUBLOOM_SESSION_ID    默认 demo-session
#   HUBLOOM_EVENT_ID      默认自动生成（推荐不设，每次新 id）
#   HUBLOOM_DEVICE_ID / HUBLOOM_CABINET_NAME / HUBLOOM_COMMUNITY_NAME / HUBLOOM_CABINET_ID

set -euo pipefail

BASE_URL="${HUBLOOM_BASE_URL:-http://127.0.0.1:8010}"
EVENT_SECRET="${HUBLOOM_EVENT_SECRET:-change-me}"
SESSION_ID="demo-session-11"
EVENT_ID="${HUBLOOM_EVENT_ID:-evt-locker-$(date +%Y%m%d-%H%M%S)-$$}"

DEVICE_ID="${HUBLOOM_DEVICE_ID:-523026567}"
CABINET_NAME="${HUBLOOM_CABINET_NAME:-B01}"
COMMUNITY_NAME="${HUBLOOM_COMMUNITY_NAME:-鄞新电力}"
CABINET_ID="${HUBLOOM_CABINET_ID:-}"

if [[ -z "${HUBLOOM_BEARER_TOKEN:-}" ]]; then
  echo "错误：请先 export HUBLOOM_BEARER_TOKEN='你的业务 Token'" >&2
  exit 1
fi

echo "POST ${BASE_URL}/v1/events"
echo "  event_id=${EVENT_ID}"
echo "  session_id=${SESSION_ID}"
echo "  deviceId=${DEVICE_ID} cabinetName=${CABINET_NAME} community=${COMMUNITY_NAME}"

curl -sS "${BASE_URL}/v1/events" \
  -H "Content-Type: application/json" \
  -H "X-Event-Secret: ${EVENT_SECRET}" \
  -d "$(cat <<EOF
{
  "event_id": "${EVENT_ID}",
  "type": "locker.created",
  "session_id": "${SESSION_ID}",
  "bearer_token": "${HUBLOOM_BEARER_TOKEN}",
  "payload": {
    "deviceId": "${DEVICE_ID}",
    "cabinetName": "${CABINET_NAME}",
    "gatedCommunityName": "${COMMUNITY_NAME}",
    "id": "${CABINET_ID}"
  }
}
EOF
)"
echo
