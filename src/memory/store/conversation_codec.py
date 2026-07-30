"""会话消息行 ↔ Message 编解码（SQLite / Postgres 共用）。"""

from __future__ import annotations

import json
from typing import Any, Mapping

from core.models import Message, Role, ToolCall


def encode_message_fields(
    message: Message,
    *,
    metadata: dict[str, Any] | None = None,
) -> tuple[str, str | None, str | None, str | None, str]:
    """返回 (content, tool_calls_json, tool_call_id, name, metadata_json)。"""
    tool_calls_json = None
    if message.tool_calls:
        tool_calls_json = json.dumps(
            [
                {"id": tc.id, "name": tc.name, "arguments": tc.arguments}
                for tc in message.tool_calls
            ],
            ensure_ascii=False,
        )

    content = (
        message.content
        if isinstance(message.content, str)
        else json.dumps(message.content, ensure_ascii=False)
    )

    meta = dict(metadata or {})
    if message.reasoning_content is not None:
        meta.setdefault("reasoning_content", message.reasoning_content)

    return (
        content,
        tool_calls_json,
        message.tool_call_id,
        message.name,
        json.dumps(meta, ensure_ascii=False),
    )


def reasoning_from_metadata(raw: str | None) -> str | None:
    if not raw:
        return None
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return None
    if not isinstance(data, dict):
        return None
    text = data.get("reasoning_content")
    if text is None:
        return None
    return str(text)


def _row_get(row: Mapping[str, Any], key: str, default: Any = None) -> Any:
    """兼容 dict 与 sqlite3.Row（Row 无 ``.get``）。"""
    try:
        value = row[key]  # type: ignore[index]
    except (KeyError, IndexError):
        return default
    return default if value is None else value


def row_to_message(row: Mapping[str, Any]) -> Message:
    role_map = {
        "system": Role.SYSTEM,
        "user": Role.USER,
        "assistant": Role.ASSISTANT,
        "tool": Role.TOOL,
    }
    role = role_map.get(str(_row_get(row, "role") or ""), Role.USER)

    tool_calls = None
    raw_tc = _row_get(row, "tool_calls")
    if raw_tc:
        if isinstance(raw_tc, (bytes, bytearray)):
            raw_tc = raw_tc.decode("utf-8")
        parsed = json.loads(raw_tc) if isinstance(raw_tc, str) else raw_tc
        tool_calls = [
            ToolCall(id=tc["id"], name=tc["name"], arguments=tc["arguments"])
            for tc in parsed
        ]

    meta_raw = _row_get(row, "metadata_json")
    if isinstance(meta_raw, (bytes, bytearray)):
        meta_raw = meta_raw.decode("utf-8")

    return Message(
        role=role,
        content=_row_get(row, "content") or "",
        tool_calls=tool_calls,
        tool_call_id=_row_get(row, "tool_call_id"),
        name=_row_get(row, "name"),
        reasoning_content=reasoning_from_metadata(
            str(meta_raw) if meta_raw is not None else None
        ),
    )
