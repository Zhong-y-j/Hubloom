"""FastAPI 请求 / 响应模型。"""

from __future__ import annotations

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
    session_id: str
    reason: str = ""


class ApplyConfigRequest(BaseModel):
    openai_api_key: str | None = None
    openai_model: str | None = None
    openai_base_url: str | None = None
    mcp_swagger_url: str | None = None
    mcp_base_url: str | None = None
    mcp_auth_scheme: str | None = None
    mcp_token: str | None = None


class ApplyConfigResponse(BaseModel):
    status: str
    swagger_url: str
    base_url: str
    group_count: int
    tool_count: int
    secret_persisted: bool = False
