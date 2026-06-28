"""FastAPI 请求 / 响应模型。"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class ChatRequest(BaseModel):
    message: str = Field(..., min_length=1, description="用户本轮输入")
    session_id: str | None = Field(
        default=None,
        description="多轮会话 ID；不传则使用默认 session",
    )
    stream: bool = Field(default=True, description="是否 SSE 流式返回")


class ChatResponse(BaseModel):
    route: str
    final_message: str
    user_reply: str = ""
    session_id: str
    intent: dict[str, Any] | None = None
    deliverable: str | None = None
    delivery_summary: str | None = None
