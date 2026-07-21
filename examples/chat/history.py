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
    a2ui: list[dict[str, Any]] | None = None
    # 正文与 A2UI 交错段；旧记录无此字段时前端回退为 content → a2ui
    answer_parts: list[dict[str, Any]] | None = None
    created_at: str | None = None


class ChatHistoryResponse(BaseModel):
    session_id: str
    messages: list[HistoryMessage]
    total: int = Field(description="messages 条数")


def _is_display_assistant(meta: dict[str, Any]) -> bool:
    """是否应在历史 UI 展示该条 assistant。"""
    if meta.get("display") is False:
        return False
    return bool(
        meta.get("route")
        or meta.get("thought")
        or meta.get("tools")
        or meta.get("a2ui")
    )


def _parse_metadata(raw: str | None) -> dict[str, Any]:
    if not raw:
        return {}
    try:
        data = json.loads(raw)
        return data if isinstance(data, dict) else {}
    except json.JSONDecodeError:
        return {}


def _coerce_a2ui(raw: Any) -> list[dict[str, Any]] | None:
    if not isinstance(raw, list) or not raw:
        return None
    out: list[dict[str, Any]] = []
    for item in raw:
        if isinstance(item, dict):
            out.append(item)
    return out or None


def _coerce_answer_parts(raw: Any) -> list[dict[str, Any]] | None:
    if not isinstance(raw, list) or not raw:
        return None
    out: list[dict[str, Any]] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        kind = str(item.get("type") or "").strip()
        if kind == "text":
            text = str(item.get("text") or "").strip()
            if text:
                part: dict[str, Any] = {"type": "text", "text": text}
                channel = str(item.get("channel") or "").strip()
                if channel in ("markdown", "a2ui"):
                    part["channel"] = channel
                out.append(part)
        elif kind == "a2ui":
            out.append({"type": "a2ui"})
    return out or None


def messages_for_display(rows: list[dict[str, str]]) -> list[HistoryMessage]:
    """过滤并清洗消息，供前端展示（含思考过程 / A2UI metadata）。"""
    out: list[HistoryMessage] = []
    for row in rows:
        role = row.get("role", "")
        if role not in ("user", "assistant"):
            continue
        content = (row.get("content") or "").strip()
        meta = _parse_metadata(row.get("metadata_json"))
        if role == "assistant" and not _is_display_assistant(meta):
            continue
        thought = (meta.get("thought") or "").strip() or None
        route = (meta.get("route") or "").strip() or None
        a2ui = _coerce_a2ui(meta.get("a2ui"))
        answer_parts = _coerce_answer_parts(meta.get("answer_parts"))
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
        if (
            role == "assistant"
            and not content
            and not thought
            and not tools
            and not a2ui
        ):
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
                a2ui=a2ui,
                answer_parts=answer_parts,
                created_at=row.get("created_at"),
            )
        )
    return out
