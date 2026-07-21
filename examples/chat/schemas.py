"""FastAPI 请求 / 响应模型。"""

from __future__ import annotations

from pydantic import BaseModel, Field


class ChatRequest(BaseModel):
    message: str = Field(..., min_length=1, description="用户本轮输入")
    session_id: str | None = Field(
        default=None,
        description="多轮会话 ID；不传则使用请求头 X-Session-Id",
    )
    stream: bool = Field(default=True, description="是否 SSE 流式返回")
    present_mode: str | None = Field(
        default=None,
        description="markdown | a2ui | auto；默认用服务端 Runtime 配置",
    )


class ChatResponse(BaseModel):
    route: str
    final_message: str
    session_id: str
    reason: str = ""
    answer_parts: list[dict] | None = None


class McpStatusResponse(BaseModel):
    status: str
    mcp_ready: bool
    swagger_url: str = ""
    base_url: str = ""
    group_count: int = 0
    tool_count: int = 0
    detail: str = ""
