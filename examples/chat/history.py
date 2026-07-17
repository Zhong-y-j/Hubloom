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
    # 本轮落库的 A2UI 消息（metadata.a2ui），供前端回放渲染
    a2ui: list[dict[str, Any]] | None = None
    created_at: str | None = None


class ChatHistoryResponse(BaseModel):
    session_id: str
    messages: list[HistoryMessage]
    total: int = Field(description="messages 条数")


def _is_display_assistant(meta: dict[str, Any]) -> bool:
    """是否应在历史 UI 展示该条 assistant。

    Thought 执行期会把带 tool_calls 的中间进度写入会话库（供多轮 recall），
    但只有带 route / thought / tools / a2ui 的条目才是本轮最终展示块。
    """
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


def messages_for_display(rows: list[dict[str, str]]) -> list[HistoryMessage]:
    """过滤并清洗消息，供前端展示（含思考过程 / A2UI metadata）。"""
    from agents.a2ui_bind import normalize_a2ui_messages

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
        if a2ui:
            a2ui = normalize_a2ui_messages(a2ui)
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
                created_at=row.get("created_at"),
            )
        )
    return out
