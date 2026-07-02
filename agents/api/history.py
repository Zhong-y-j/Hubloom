"""对话历史 API 辅助。"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class HistoryMessage(BaseModel):
    role: Literal["user", "assistant"]
    content: str
    created_at: str | None = None


class ChatHistoryResponse(BaseModel):
    session_id: str
    messages: list[HistoryMessage]
    total: int = Field(description="messages 条数")


def messages_for_display(rows: list[dict[str, str]]) -> list[HistoryMessage]:
    """过滤并清洗消息，供前端展示。"""
    out: list[HistoryMessage] = []
    for row in rows:
        role = row.get("role", "")
        if role not in ("user", "assistant"):
            continue
        content = (row.get("content") or "").strip()
        if not content:
            continue
        out.append(
            HistoryMessage(
                role=role,  # type: ignore[arg-type]
                content=content,
                created_at=row.get("created_at"),
            )
        )
    return out
