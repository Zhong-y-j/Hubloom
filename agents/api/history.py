"""对话历史 API 辅助。"""

from __future__ import annotations

import json
from typing import Any, Literal

from pydantic import BaseModel, Field


class ToolHistoryItem(BaseModel):
    title: str
    body: str = ""


class HistoryMessage(BaseModel):
    role: Literal["user", "assistant"]
    content: str
    thought: str | None = None
    tools: list[ToolHistoryItem] = Field(default_factory=list)
    route: str | None = None
    created_at: str | None = None


class ChatHistoryResponse(BaseModel):
    session_id: str
    messages: list[HistoryMessage]
    total: int = Field(description="messages 条数")


def _parse_metadata(raw: str | None) -> dict[str, Any]:
    if not raw:
        return {}
    try:
        data = json.loads(raw)
        return data if isinstance(data, dict) else {}
    except json.JSONDecodeError:
        return {}


def messages_for_display(rows: list[dict[str, str]]) -> list[HistoryMessage]:
    """过滤并清洗消息，供前端展示（含思考过程 metadata）。"""
    out: list[HistoryMessage] = []
    for row in rows:
        role = row.get("role", "")
        if role not in ("user", "assistant"):
            continue
        content = (row.get("content") or "").strip()
        meta = _parse_metadata(row.get("metadata_json"))
        thought = (meta.get("thought") or "").strip() or None
        route = (meta.get("route") or "").strip() or None
        tools_raw = meta.get("tools") or []
        tools: list[ToolHistoryItem] = []
        if isinstance(tools_raw, list):
            for item in tools_raw:
                if not isinstance(item, dict):
                    continue
                title = str(item.get("title") or "").strip()
                if not title:
                    continue
                tools.append(
                    ToolHistoryItem(
                        title=title,
                        body=str(item.get("body") or ""),
                    )
                )
        if role == "assistant" and not content and not thought and not tools:
            continue
        if role == "user" and not content:
            continue
        out.append(
            HistoryMessage(
                role=role,  # type: ignore[arg-type]
                content=content,
                thought=thought,
                tools=tools,
                route=route,
                created_at=row.get("created_at"),
            )
        )
    return out
