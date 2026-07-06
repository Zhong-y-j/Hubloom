from __future__ import annotations

import json
from typing import Any

from agents.api.context import get_bearer_token
from mcp_adapter import MCPToolClient
from mcp_adapter.auth import resolve_auth_token
from tools.base import BaseTool


def _schema_expects_object(schema: dict[str, Any]) -> bool:
    if schema.get("type") == "object":
        return True
    for item in schema.get("anyOf") or []:
        if isinstance(item, dict) and item.get("type") == "object":
            return True
    return False


def _coerce_arg(value: Any, schema: dict[str, Any]) -> Any:
    """按 JSON Schema 类型归一化 LLM 工具参数（尤其 object 常被传成字符串）。"""
    if not isinstance(schema, dict) or not _schema_expects_object(schema):
        return value

    if value is None:
        return {}
    if isinstance(value, str):
        text = value.strip()
        if not text or text.lower() in {"none", "null"}:
            return {}
        try:
            parsed = json.loads(text)
            if isinstance(parsed, dict):
                return parsed
        except json.JSONDecodeError:
            return value
    return value


def _normalize_payload(payload: dict[str, Any]) -> dict[str, Any]:
    """无参 API 调用时省略空 arguments，与 LLM 不传该字段的行为一致。"""
    if payload.get("arguments") == {}:
        return {k: v for k, v in payload.items() if k != "arguments"}
    return payload


def _coerce_args(parameters: dict[str, Any], kwargs: dict[str, Any]) -> dict[str, Any]:
    props = parameters.get("properties") if isinstance(parameters, dict) else None
    if not isinstance(props, dict):
        return dict(kwargs)

    out = dict(kwargs)
    for key, prop_schema in props.items():
        if key in out:
            out[key] = _coerce_arg(out[key], prop_schema)
    return out


def _filter_args(parameters: dict[str, Any], kwargs: dict[str, Any]) -> dict[str, Any]:
    """只转发 JSON Schema ``properties`` 里声明的字段，减少无关参数触发的校验错误。"""
    props = parameters.get("properties") if isinstance(parameters, dict) else None
    if not isinstance(props, dict) or not props:
        return dict(kwargs)
    allowed = set(props.keys())
    return {k: v for k, v in kwargs.items() if k in allowed}


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
        payload = _normalize_payload(
            _filter_args(
                self.parameters,
                _coerce_args(self.parameters, kwargs),
            )
        )
        result = await self._client.execute_tool(
            self.name,
            payload,
            auth_token=resolve_auth_token(get_bearer_token()),
        )
        if not result.transport_ok:
            raise RuntimeError(result.error or "MCP 工具调用失败")
        return result.to_llm_text()
