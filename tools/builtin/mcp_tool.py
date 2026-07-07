from __future__ import annotations

import json
from typing import Any

from agents.api.request_context import get_bearer_token, get_mcp_auth_scheme
from mcp_adapter import MCPToolClient
from mcp_adapter.auth import auth_trace, resolve_auth_token
from tools.base import BaseTool


def _filter_args(parameters: dict[str, Any], kwargs: dict[str, Any]) -> dict[str, Any]:
    """只转发 JSON Schema ``properties`` 里声明的字段，减少无关参数触发的校验错误。"""
    props = parameters.get("properties") if isinstance(parameters, dict) else None
    if not isinstance(props, dict) or not props:
        return dict(kwargs)
    allowed = set(props.keys())
    return {k: v for k, v in kwargs.items() if k in allowed}


def _coerce_nested_arguments(tool_name: str, payload: dict[str, Any]) -> dict[str, Any]:
    """LLM 常把 call_tool.arguments 序列化成 JSON 字符串，网关要求 dict。"""
    if tool_name != "call_tool":
        return payload
    raw = payload.get("arguments")
    if not isinstance(raw, str) or not raw.strip():
        return payload
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        return payload
    if not isinstance(parsed, dict):
        return payload
    out = dict(payload)
    out["arguments"] = parsed
    return out


class MCPTool(BaseTool):
    """一个代理工具，代表远程 MCP Server 上的一个具体工具。"""

    def __init__(
        self,
        name: str,
        description: str,
        parameters: dict[str, Any],
        client: MCPToolClient,
    ):
        self.name = name
        self.description = description
        self.parameters = parameters
        self._client = client

    async def execute(self, **kwargs: Any) -> str:
        """执行远程工具；返回传输层 JSON 文本，业务语义由 LLM 解读。"""
        payload = _filter_args(
            self.parameters,
            kwargs,
        )
        payload = _coerce_nested_arguments(self.name, payload)

        auth_token = resolve_auth_token(get_bearer_token())
        auth_scheme = (get_mcp_auth_scheme() or "").strip() or None
        auth_trace(
            "agent_tool",
            tool=self.name,
            has_token=bool(auth_token),
            scheme=auth_scheme,
        )

        result = await self._client.execute_tool(
            self.name,
            payload,
            auth_token=auth_token,
            auth_scheme=auth_scheme,
        )
        if not result.transport_ok:
            raise RuntimeError(result.error or "MCP 工具调用失败")
        return result.to_llm_text()
