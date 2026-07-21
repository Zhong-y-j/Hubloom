#!/usr/bin/env python3
"""Hubloom 主入口 — 启动 HTTP 聊天演示。

在仓库根执行::

    uv sync
    PYTHONPATH=src:. uv run python main.py
"""

from examples.chat.app import main

if __name__ == "__main__":
    main()
