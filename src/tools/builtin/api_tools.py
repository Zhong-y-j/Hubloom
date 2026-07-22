"""Agent 侧 API 元工具：只暴露 list_api / call_api，背后转发到单个全量 MCP。"""

from __future__ import annotations

import json
from typing import Any

from context import get_bearer_token, get_mcp_auth_scheme
from mcp_adapter.auth import auth_trace, resolve_auth_token
from mcp_adapter.client.session import MCPToolClient
from mcp_adapter.gateway.catalog import GatewayCatalog, mcp_tool_name
from tools.base import BaseTool


def _coerce_arguments(raw: Any) -> dict[str, Any]:
    if raw is None:
        return {}
    if isinstance(raw, dict):
        return raw
    if isinstance(raw, str) and raw.strip():
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError:
            return {}
        if isinstance(parsed, dict):
            return parsed
    return {}


def _resolve_tool_name(catalog: GatewayCatalog, tag: str, tool_name: str) -> str:
    group = catalog.get_group(tag)
    if not group:
        raise ValueError(f"未知分组 tag: {tag!r}")

    name = (tool_name or "").strip()
    if not name:
        raise ValueError(f"工具名不能为空（分组 {tag!r}）")

    if name in group.tool_names:
        return name

    short = mcp_tool_name(name)
    if short in group.tool_names:
        return short

    preview = ", ".join(group.tool_names[:5])
    raise ValueError(f"工具 {tool_name!r} 不属于分组 {tag!r}；示例: {preview}...")


class ListAPITool(BaseTool):
    """按 OpenAPI tag 列出该分组内的业务 API 工具（含 parameters schema）。"""

    name = "list_api"
    description = (
        "列出指定 tag 分组内的业务 API 工具（含 parameters JSON Schema）。"
        "仅用于发现工具名与参数，不能代替实际业务调用。"
        "tag 为 OpenAPI 分组名，见 system prompt 中的「API 分组」目录。"
    )
    parameters = {
        "type": "object",
        "properties": {
            "tag": {
                "type": "string",
                "description": "OpenAPI tag / API 分组名",
            },
        },
        "required": ["tag"],
    }

    def __init__(self, catalog: GatewayCatalog, client: MCPToolClient) -> None:
        self._catalog = catalog
        self._client = client
        self._all_tools_cache: list[dict[str, Any]] | None = None

    async def _all_tools(self) -> list[dict[str, Any]]:
        if self._all_tools_cache is None:
            self._all_tools_cache = await self._client.list_tools()
        return self._all_tools_cache

    async def execute(self, tag: str = "", **_: Any) -> str:
        key = (tag or "").strip()
        if not key:
            raise ValueError("tag 不能为空")
        group = self._catalog.get_group(key)
        if group is None:
            raise ValueError(f"未知分组 tag: {key!r}")

        allowed = set(group.tool_names)
        tools = [t for t in await self._all_tools() if t.get("name") in allowed]
        return json.dumps(tools, ensure_ascii=False, indent=2)


class CallAPITool(BaseTool):
    """按 tag 校验后，调用全量 MCP 上的业务 API。"""

    name = "call_api"
    description = (
        "调用指定分组内的实际业务接口（创建/查询/更新/删除等均须通过本工具）。"
        "tag 见 system prompt 中的「API 分组」；tool_name 来自 list_api；"
        "arguments 为该工具的参数对象（JSON object），无参时可省略。"
    )
    parameters = {
        "type": "object",
        "properties": {
            "tag": {
                "type": "string",
                "description": "OpenAPI tag / API 分组名",
            },
            "tool_name": {
                "type": "string",
                "description": "业务工具名（来自 list_api）",
            },
            "arguments": {
                "type": "object",
                "description": "工具参数对象；无参时可省略",
            },
        },
        "required": ["tag", "tool_name"],
    }

    def __init__(self, catalog: GatewayCatalog, client: MCPToolClient) -> None:
        self._catalog = catalog
        self._client = client

    async def execute(
        self,
        tag: str = "",
        tool_name: str = "",
        arguments: Any = None,
        **_: Any,
    ) -> str:
        key = (tag or "").strip()
        if not key:
            raise ValueError("tag 不能为空")
        if self._catalog.get_group(key) is None:
            raise ValueError(f"未知分组 tag: {key!r}")

        resolved = _resolve_tool_name(self._catalog, key, tool_name)
        payload = _coerce_arguments(arguments)

        auth_token = resolve_auth_token(get_bearer_token())
        auth_scheme = (get_mcp_auth_scheme() or "").strip() or None
        auth_trace(
            "agent_api_call",
            tag=key,
            tool_name=resolved,
            has_token=bool(auth_token),
            scheme=auth_scheme,
        )

        result = await self._client.execute_tool(
            resolved,
            payload,
            auth_token=auth_token,
            auth_scheme=auth_scheme,
        )
        if not result.transport_ok:
            raise RuntimeError(result.error or "MCP 工具调用失败")
        return result.to_llm_text()


def build_api_tools(
    catalog: GatewayCatalog,
    client: MCPToolClient,
) -> list[BaseTool]:
    """构造 Agent 可见的两个 API 元工具（共享同一全量 MCP 客户端）。"""
    return [
        ListAPITool(catalog, client),
        CallAPITool(catalog, client),
    ]
