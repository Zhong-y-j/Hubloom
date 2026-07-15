#!/usr/bin/env bash
# 一键启动差旅三系统演示（交通 → 景点 → 酒店，A2A 三向互连）
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

echo "=== 差旅演示：启动交通 ==="
"$SCRIPT_DIR/start-transport-demo.sh"

echo ""
echo "=== 差旅演示：启动景点 ==="
"$SCRIPT_DIR/start-attraction-demo.sh"

echo ""
echo "=== 差旅演示：启动酒店 ==="
"$SCRIPT_DIR/start-hotel-demo.sh"

echo ""
echo "=========================================="
echo "  三系统已全部启动"
echo "=========================================="
echo ""
echo "跨系统演示（任选一个聊天页作为入口）："
echo "  交通        http://127.0.0.1:9003/chat"
echo "  景点        http://127.0.0.1:9004/chat"
echo "  酒店        http://127.0.0.1:9001/chat"
echo ""
echo "单系统入口："
echo "  交通        http://127.0.0.1:9003/login"
echo "  景点        http://127.0.0.1:9004/login"
echo "  酒店        http://127.0.0.1:9001/login"
echo ""
echo "Hubloom："
echo "  交通 8003   http://127.0.0.1:8003/.well-known/agent-card.json"
echo "  景点 8004   http://127.0.0.1:8004/.well-known/agent-card.json"
echo "  酒店 8001   http://127.0.0.1:8001/.well-known/agent-card.json"
echo "              （各实例出站 A2A → 另外两个 Hubloom）"
echo ""
echo "停止：./examples/travel/scripts/stop-travel-demo.sh"
