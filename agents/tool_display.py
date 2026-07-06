"""工具调用在 UI / SSE 中的展示名解析。"""

from __future__ import annotations

from typing import Any


def resolve_tool_display_name(
    tool_name: str,
    args: dict[str, Any] | None = None,
) -> str:
    """将 MCP 元工具名映射为更易读的业务工具名。

    ``call_tool`` → ``arguments.tool_name``（如 ``GatedCommunity_Create``）。
    """
    name = (tool_name or "").strip() or "tool"
    if not isinstance(args, dict):
        return name

    if name == "call_tool":
        inner = args.get("tool_name")
        if isinstance(inner, str) and inner.strip():
            return inner.strip()

    return name
