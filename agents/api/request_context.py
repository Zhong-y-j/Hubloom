"""HTTP 请求上下文：单次 chat 请求内的客户端配置与 MCP 鉴权。"""

from __future__ import annotations

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


def clear_request_context() -> None:
    _bearer_token.set(None)
    _session_id.set(None)
    _openai_api_key.set(None)
    _openai_model.set(None)
    _openai_base_url.set(None)
    _mcp_auth_scheme.set(None)
    _mcp_swagger_url.set(None)
    _mcp_base_url.set(None)
