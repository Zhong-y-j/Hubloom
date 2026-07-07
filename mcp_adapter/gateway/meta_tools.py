"""网关元工具：Agent 只看到 list_tools / call_tool，不直接暴露全量 OpenAPI tools。"""

from __future__ import annotations

import json
from typing import Any

from fastmcp import FastMCP

from mcp_adapter.auth import get_request_auth_token
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
        if "structured" not in out:
            try:
                parsed = json.loads(joined)
                if isinstance(parsed, (dict, list)):
                    out["structured"] = parsed
                else:
                    out["text"] = joined
            except json.JSONDecodeError:
                out["text"] = joined

    return out


def register_meta_tools(
    mcp: FastMCP,
    router: BackendRouter,
) -> None:
    """把元工具注册到网关 FastMCP 实例。"""

    @mcp.tool(
        description=(
            "列出指定 tag 分组内的工具（含 parameters JSON Schema）。"
            "tag 为 OpenAPI 分组名，见 system prompt 中的「API 分组」目录。"
        ),
        run_in_thread=False,
    )
    async def list_tools(tag: str) -> list[dict[str, Any]]:
        return await router.list_tools(tag)

    @mcp.tool(
        description=(
            "调用指定分组内的工具。"
            "tag 见 system prompt 中的「API 分组」；tool_name 来自 list_tools；"
            "arguments 为该工具的参数对象（JSON object），无参时可省略。"
        ),
        run_in_thread=False,
    )
    async def call_tool(
        tag: str,
        tool_name: str,
        arguments: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        result = await router.call_tool(
            tag,
            tool_name,
            arguments,
            auth_token=get_request_auth_token(),
        )
        return _format_call_tool_result(result)
