"""网关元工具：Agent 只看到这 3 个工具，不直接暴露全量 OpenAPI tools。"""

from __future__ import annotations

import json
from typing import Any

from fastmcp import FastMCP

from mcp_adapter.gateway.catalog import GatewayCatalog
from mcp_adapter.gateway.router import BackendRouter


def _format_call_tool_result(result: Any) -> dict[str, Any]:
    """把 MCP CallToolResult 转成 LLM 易读的 dict。"""
    out: dict[str, Any] = {
        "isError": bool(getattr(result, "isError", False)),
    }

    structured = getattr(result, "structuredContent", None)
    if structured is not None:
        out["structured"] = structured

    texts: list[str] = []
    for block in getattr(result, "content", None) or []:
        text = getattr(block, "text", None)
        if text:
            texts.append(text)

    if texts:
        joined = "\n".join(texts)
        out["text"] = joined
        if "structured" not in out:
            try:
                parsed = json.loads(joined)
                if isinstance(parsed, (dict, list)):
                    out["structured"] = parsed
            except json.JSONDecodeError:
                pass

    return out


def register_meta_tools(
    mcp: FastMCP,
    catalog: GatewayCatalog,
    router: BackendRouter,
) -> None:
    """把元工具注册到网关 FastMCP 实例。"""

    @mcp.tool(
        description=(
            "列出 API 分组（OpenAPI tag）。"
            "先调用此工具了解有哪些分组，再用 list_tools 查看组内工具。"
        )
    )
    async def list_groups() -> list[dict[str, Any]]:
        running = set(router.pool.running_tags())
        groups: list[dict[str, Any]] = []
        for tag in catalog.list_tags():
            group = catalog.get_group(tag)
            if not group:
                continue
            groups.append(
                {
                    "tag": tag,
                    "description": group.description,
                    "tool_count": group.tool_count,
                    "running": tag in running,
                }
            )
        return groups

    @mcp.tool(
        description=(
            "列出指定 tag 分组内的工具（含 parameters JSON Schema）。"
            "tag 必须来自 list_groups 的返回值。"
        )
    )
    async def list_tools(tag: str) -> list[dict[str, Any]]:
        return await router.list_tools(tag)

    @mcp.tool(
        description=(
            "调用指定分组内的工具。"
            "tag 来自 list_groups；tool_name 来自 list_tools；"
            "arguments 为该工具的参数对象。"
        )
    )
    async def call_tool(
        tag: str,
        tool_name: str,
        arguments: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        result = await router.call_tool(tag, tool_name, arguments)
        return _format_call_tool_result(result)
