"""FastAPI 请求 / 响应模型。"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator


class ChatAction(BaseModel):
    """本轮人机动作（须与 waiting 的 run_id 一致）。"""

    type: Literal["submit", "cancel"] = Field(description="提交或取消")
    name: str = Field(
        ...,
        min_length=1,
        description="动作名，如 A2UI 按钮名 confirm_add_community",
    )
    payload: dict[str, Any] = Field(
        default_factory=dict,
        description="表单字段（多为原 A2UI context）",
    )
    surface_id: str | None = None
    source_component_id: str | None = None
    tool_call_id: str | None = Field(
        default=None,
        description="与 waiting 时下发的 toolCallId 一致（可选，有则校验）",
    )


class ChatRequest(BaseModel):
    message: str | None = Field(
        default=None,
        description="用户自然语言；与 action 二选一",
    )
    action: ChatAction | None = Field(
        default=None,
        description="表单提交/取消；须同时传 run_id",
    )
    run_id: str | None = Field(
        default=None,
        description="action 必填：绑定本轮 waiting 的 run_id",
    )
    session_id: str | None = Field(
        default=None,
        description="多轮会话 ID；不传则使用请求头 X-Session-Id",
    )
    stream: bool = Field(default=True, description="是否 SSE 流式返回")
    present_mode: str | None = Field(
        default=None,
        description="markdown | a2ui | auto；默认用服务端 Runtime 配置",
    )

    @model_validator(mode="after")
    def _message_xor_action(self) -> ChatRequest:
        msg = (self.message or "").strip()
        has_msg = bool(msg)
        has_act = self.action is not None
        if has_msg == has_act:
            raise ValueError("须且仅能提供 message 或 action 之一")
        if has_act:
            rid = (self.run_id or "").strip()
            if not rid:
                raise ValueError("action 请求必须带 run_id")
            self.run_id = rid
            # 规范化 message 为空
            self.message = None
        else:
            self.message = msg
            self.run_id = (self.run_id or "").strip() or None
        return self


class ChatResponse(BaseModel):
    route: str
    final_message: str
    session_id: str
    reason: str = ""
    answer_parts: list[dict] | None = None
    run_id: str | None = Field(
        default=None,
        description="本轮 Agent run_id；若本轮有待填表单，提交/取消须带同一 run_id",
    )


class McpStatusResponse(BaseModel):
    status: str
    mcp_ready: bool
    swagger_url: str = ""
    base_url: str = ""
    group_count: int = 0
    tool_count: int = 0
    detail: str = ""


class EventIngestResponse(BaseModel):
    """POST /v1/events 同步响应。"""

    event_id: str
    session_id: str
    type: str
    ok: bool
    duplicate: bool = False
    summary: str = ""
    error: str | None = None
    turn_count: int = 0
