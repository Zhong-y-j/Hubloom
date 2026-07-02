#!/usr/bin/env python3
"""Agent Cortex（灵枢）主入口 — 启动 HTTP 服务。

PYTHONPATH=. uv run python main.py 
"""

from agents.api.app import main

if __name__ == "__main__":
    main()
