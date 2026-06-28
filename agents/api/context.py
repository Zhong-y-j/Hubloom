"""HTTP 请求上下文（Token / session，供后续 MCP 透传扩展）。"""

from __future__ import annotations

import contextvars

_bearer_token: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "bearer_token", default=None
)
_session_id: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "session_id", default=None
)


def set_request_context(
    *,
    bearer_token: str | None = None,
    session_id: str | None = None,
) -> None:
    _bearer_token.set(bearer_token)
    _session_id.set(session_id)


def get_bearer_token() -> str | None:
    return _bearer_token.get()


def get_session_id() -> str | None:
    return _session_id.get()


def clear_request_context() -> None:
    _bearer_token.set(None)
    _session_id.set(None)
