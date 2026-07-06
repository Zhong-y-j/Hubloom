"""解析 MCP CallToolResult → ToolTransportResult。"""

from __future__ import annotations

import json
from typing import Any

from tools.tool_result import ToolTransportResult, build_transport_result


def tool_input_schema(tool: Any) -> dict[str, Any]:
    """兼容 MCP SDK 中 Tool 的 schema 字段命名。"""
    raw = getattr(tool, "input_schema", None) or getattr(tool, "inputSchema", None)
    if raw is None:
        return {"type": "object", "properties": {}}
    if isinstance(raw, dict):
        return raw
    if hasattr(raw, "model_dump"):
        return raw.model_dump(by_alias=True, exclude_none=True)
    return dict(raw)


def extract_text_content(result: Any) -> str:
    parts: list[str] = []
    for item in getattr(result, "content", None) or []:
        text = getattr(item, "text", None)
        if isinstance(text, str):
            parts.append(text)
        else:
            parts.append(str(item))
    return "\n".join(parts).strip()


def read_http_meta(result: Any) -> tuple[int | None, str | None]:
    meta = getattr(result, "meta", None)
    if not isinstance(meta, dict):
        return None, None

    status: int | None = None
    reason: str | None = None

    raw_status = meta.get("http_status")
    if raw_status is not None:
        try:
            status = int(raw_status)
        except (TypeError, ValueError):
            status = None
    if isinstance(meta.get("http_reason"), str):
        reason = meta["http_reason"]
    return status, reason


def parse_call_tool_result(
    result: Any,
    *,
    tool_name: str,
    arguments: dict[str, Any],
) -> ToolTransportResult:
    if getattr(result, "isError", False):
        err_text = extract_text_content(result)
        return build_transport_result(
            tool_name=tool_name,
            arguments=arguments,
            transport_ok=False,
            error=err_text or f"Tool {tool_name!r} returned MCP error",
        )

    http_status, http_reason = read_http_meta(result)
    body = ""

    structured = getattr(result, "structuredContent", None)
    text_body = extract_text_content(result)

    if text_body:
        try:
            parsed_text = json.loads(text_body)
            if isinstance(parsed_text, dict) and "code" in parsed_text:
                body = text_body
                structured = parsed_text
            elif isinstance(structured, dict):
                payload = {
                    k: v
                    for k, v in structured.items()
                    if k not in {"_http_status", "_http_reason"}
                }
                if payload:
                    body = json.dumps(payload, ensure_ascii=False)
        except json.JSONDecodeError:
            body = text_body

    if not body and isinstance(structured, dict):
        if http_status is None and "_http_status" in structured:
            try:
                http_status = int(structured["_http_status"])
            except (TypeError, ValueError):
                http_status = None
        if http_reason is None and isinstance(structured.get("_http_reason"), str):
            http_reason = structured["_http_reason"]
        payload = {
            k: v
            for k, v in structured.items()
            if k not in {"_http_status", "_http_reason"}
        }
        if payload:
            body = json.dumps(payload, ensure_ascii=False)
        elif http_status is not None:
            body = ""

    if not body and isinstance(structured, (dict, list)):
        body = json.dumps(structured, ensure_ascii=False)

    if not body:
        body = extract_text_content(result)

    return build_transport_result(
        tool_name=tool_name,
        arguments=arguments,
        transport_ok=True,
        http_status=http_status,
        http_reason=http_reason,
        body=body,
    )
