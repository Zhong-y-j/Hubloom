#!/usr/bin/env bash
# 一键停止差旅三系统演示
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

echo "=== 差旅演示：停止酒店 ==="
"$SCRIPT_DIR/stop-hotel-demo.sh"

echo ""
echo "=== 差旅演示：停止交通 ==="
"$SCRIPT_DIR/stop-transport-demo.sh"

echo ""
echo "=== 差旅演示：停止景点 ==="
"$SCRIPT_DIR/stop-attraction-demo.sh"

echo ""
echo "差旅三系统演示已全部停止"
