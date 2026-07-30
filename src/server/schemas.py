"""Hubloom Serve 请求 / 响应模型（无 A2UI / AG-UI）。"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


class ChatRequest(BaseModel):
    message: str = Field(..., min_length=1, description="用户自然语言")
    session_id: str | None = Field(
        default=None,
        description="会话 ID；也可放请求头 X-Session-Id",
    )
    stream: bool = Field(default=True, description="SSE 流式（推荐）")
    wait_profile: str | None = Field(
        default=None,
        description="interactive | turn_based | no_wait；默认用配置 agent.default_wait_profile",
    )


class ResumeRequest(BaseModel):
    session_id: str | None = Field(
        default=None,
        description="会话 ID；也可放请求头 X-Session-Id",
    )
    user_reply: str = Field(..., min_length=1, description="用户对追问/确认的回复")
    run_id: str | None = Field(
        default=None,
        description="awaiting_user 事件里的 await_run_id（建议传）",
    )
    await_token: str | None = Field(
        default=None,
        description="awaiting_user 事件里的 await_token（建议传）",
    )
    stream: bool = Field(default=True, description="SSE 流式（推荐）")


class ChatSyncResponse(BaseModel):
    session_id: str
    status: str
    content: str = ""
    ok: bool = True
    error: str = ""
    journal_run_id: str = ""
    evidence_ids: list[str] = Field(default_factory=list)
    await_token: str = ""
    wait_profile: str = ""
    pending: dict[str, Any] | None = None
    think_rounds: int = 0
    tool_calls: int = 0
    elapsed_ms: int = 0


class HistoryMessage(BaseModel):
    role: Literal["user", "assistant"]
    content: str
    created_at: str | None = None
    source: str | None = None


class ChatHistoryResponse(BaseModel):
    session_id: str
    messages: list[HistoryMessage]
    total: int


class McpStatusResponse(BaseModel):
    status: str
    mcp_ready: bool
    swagger_url: str = ""
    base_url: str = ""
    group_count: int = 0
    tool_count: int = 0
    detail: str = ""
