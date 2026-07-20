"""请求上下文：单次对话内的客户端配置与 MCP 鉴权（Hubloom / 工具共用）。"""

from __future__ import annotations

import asyncio
import contextvars

_bearer_token: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "bearer_token", default=None
)
_session_id: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "session_id", default=None
)
_openai_api_key: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "openai_api_key", default=None
)
_openai_model: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "openai_model", default=None
)
_openai_base_url: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "openai_base_url", default=None
)
_mcp_auth_scheme: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "mcp_auth_scheme", default=None
)
_mcp_swagger_url: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "mcp_swagger_url", default=None
)
_mcp_base_url: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "mcp_base_url", default=None
)
# 出站 A2A：Thought 挂上队列后，delegate_task 把远程过程推进来供 SSE 转发
_remote_process_queue: contextvars.ContextVar[asyncio.Queue | None] = (
    contextvars.ContextVar("remote_process_queue", default=None)
)
_remote_process_call_id: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "remote_process_call_id", default=None
)
_remote_process_agent_id: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "remote_process_agent_id", default=None
)
# 入站 A2A：为 True 时禁止再 delegate_task，避免互委托死循环
_a2a_inbound: contextvars.ContextVar[bool] = contextvars.ContextVar(
    "a2a_inbound", default=False
)


def set_request_context(
    *,
    bearer_token: str | None = None,
    session_id: str | None = None,
    openai_api_key: str | None = None,
    openai_model: str | None = None,
    openai_base_url: str | None = None,
    mcp_auth_scheme: str | None = None,
    mcp_swagger_url: str | None = None,
    mcp_base_url: str | None = None,
) -> None:
    _bearer_token.set(bearer_token)
    _session_id.set(session_id)
    _openai_api_key.set(openai_api_key)
    _openai_model.set(openai_model)
    _openai_base_url.set(openai_base_url)
    _mcp_auth_scheme.set(mcp_auth_scheme)
    _mcp_swagger_url.set(mcp_swagger_url)
    _mcp_base_url.set(mcp_base_url)


def get_bearer_token() -> str | None:
    return _bearer_token.get()


def get_session_id() -> str | None:
    return _session_id.get()


def get_openai_api_key() -> str | None:
    return _openai_api_key.get()


def get_openai_model() -> str | None:
    return _openai_model.get()


def get_openai_base_url() -> str | None:
    return _openai_base_url.get()


def get_mcp_auth_scheme() -> str | None:
    return _mcp_auth_scheme.get()


def get_mcp_swagger_url() -> str | None:
    return _mcp_swagger_url.get()


def get_mcp_base_url() -> str | None:
    return _mcp_base_url.get()


def set_a2a_inbound(enabled: bool = True) -> None:
    """标记当前请求是否为入站 A2A 回合。"""
    _a2a_inbound.set(bool(enabled))


def is_a2a_inbound() -> bool:
    return bool(_a2a_inbound.get())


def set_remote_process_sink(
    queue: asyncio.Queue,
    *,
    call_id: str,
    agent_id: str = "",
) -> None:
    """Thought 在执行 delegate_task 前挂上过程队列。"""
    _remote_process_queue.set(queue)
    _remote_process_call_id.set(call_id)
    _remote_process_agent_id.set(agent_id)


def clear_remote_process_sink() -> None:
    _remote_process_queue.set(None)
    _remote_process_call_id.set(None)
    _remote_process_agent_id.set(None)


def emit_remote_process(
    channel: str,
    text: str = "",
    *,
    status: str = "",
) -> None:
    """工具内同步回调：把远程过程推进 Thought 的队列（无 sink 则忽略）。"""
    queue = _remote_process_queue.get()
    call_id = _remote_process_call_id.get()
    if queue is None or not call_id:
        return
    from agent.events import RemoteProcessEvent

    ev = RemoteProcessEvent(
        call_id=call_id,
        agent_id=_remote_process_agent_id.get() or "",
        channel=(channel or "").strip() or "trace",
        delta=text or "",
        status=(status or "").strip(),
    )
    try:
        queue.put_nowait(ev)
    except asyncio.QueueFull:
        pass


def clear_request_context() -> None:
    _bearer_token.set(None)
    _session_id.set(None)
    _openai_api_key.set(None)
    _openai_model.set(None)
    _openai_base_url.set(None)
    _mcp_auth_scheme.set(None)
    _mcp_swagger_url.set(None)
    _mcp_base_url.set(None)
    clear_remote_process_sink()
    _a2a_inbound.set(False)
