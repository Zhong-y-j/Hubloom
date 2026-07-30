#!/usr/bin/env python3
"""Hubloom 主入口 — 启动产品 HTTP API（Hubloom Serve）。

在仓库根执行::

    uv sync
    PYTHONPATH=src uv run python main.py
    # 或：PYTHONPATH=src uv run python -m server serve --config config/env.yaml

演示前端（可选）::

    cd examples/chat/web && npm install && npm run dev
"""

from __future__ import annotations

import sys

from server.cli import main


if __name__ == "__main__":
    argv = sys.argv[1:]
    if not argv or argv[0] != "serve":
        argv = ["serve", *argv]
    main(argv)
