#!/usr/bin/env python3
"""Agent Cortex HTTP 服务入口。

PYTHONPATH=. uv run python server.py
PYTHONPATH=. uv run uvicorn agents.api.app:app --host 0.0.0.0 --port 8000
"""

from agents.api.app import main

if __name__ == "__main__":
    main()
