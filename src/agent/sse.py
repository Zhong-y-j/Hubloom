"""兼容入口：出站 SSE 已迁至 ``agent.agui_sse``。

旧代码 ``from agent.sse import ...`` 仍可用；新代码请直接
``from agent.agui_sse import ...``。
"""

from __future__ import annotations

from agent.agui_sse import (  # noqa: F401
    compact_tool_result,
    event_to_sse,
    format_sse,
    run_started_payload,
    turn_complete_payload,
)

__all__ = [
    "compact_tool_result",
    "event_to_sse",
    "format_sse",
    "run_started_payload",
    "turn_complete_payload",
]
