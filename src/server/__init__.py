"""Hubloom HTTP 服务：产品 API 面（无 A2UI / AG-UI）。

启动::

    PYTHONPATH=src .venv/bin/python -m server serve --config config/env.yaml
    # 或
    PYTHONPATH=src .venv/bin/hubloom serve --config config/env.yaml
"""

from __future__ import annotations

from server.app import create_app

__all__ = ["create_app"]
