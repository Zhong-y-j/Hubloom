"""MCP 工具调用日志（写入 observability / logs/debug.log）。"""

from __future__ import annotations

import json
import os
from typing import Any

from observability import log as _log

_DEFAULT_CLIP = 1200


def _enabled() -> bool:
    if os.getenv("CORTEX_AGENT_LOG", "").lower() in ("1", "true", "yes"):
        return True
    return os.getenv("CORTEX_MCP_LOG", "").lower() in ("1", "true", "yes")


def clip_text(text: str | None, n: int = _DEFAULT_CLIP) -> str:
    s = (text or "").strip().replace("\n", "\\n")
    if len(s) <= n:
        return s
    return s[:n] + f"…(+{len(s) - n})"


def dumps_clip(value: Any, n: int = _DEFAULT_CLIP) -> str:
    try:
        raw = json.dumps(value, ensure_ascii=False, default=str)
    except (TypeError, ValueError):
        raw = str(value)
    return clip_text(raw, n)


def mcp_log(message: str, /, **fields: Any) -> None:
    if not _enabled():
        return
    _log(f"mcp {message}", **fields)
