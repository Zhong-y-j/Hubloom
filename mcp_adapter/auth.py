"""MCP 鉴权透传：用户 Bearer → MCP meta → 下游 HTTP Authorization。"""

from __future__ import annotations

import contextvars
import os
from typing import Any

from dotenv import load_dotenv
from fastmcp.server.middleware import CallNext, Middleware, MiddlewareContext
import mcp.types as mt

AUTH_META_KEY = "io.cortex/auth"

_request_auth_token: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "mcp_request_auth_token",
    default=None,
)


def auth_scheme() -> str:
    """认证前缀，默认 Bearer；可通过 MCP_AUTH_SCHEME 覆盖（如 JWT）。"""
    load_dotenv()
    return (os.getenv("MCP_AUTH_SCHEME") or "Bearer").strip()


def static_auth_token() -> str | None:
    """环境变量中的服务级 Token（无用户透传时的回退）。"""
    load_dotenv()
    token = (os.getenv("MCP_TOKEN") or "").strip()
    return token or None


def resolve_auth_token(token: str | None) -> str | None:
    """优先使用调用方传入的 token，否则回退 MCP_TOKEN。"""
    explicit = (token or "").strip()
    if explicit:
        return explicit
    return static_auth_token()


def build_authorization_header(token: str | None) -> str | None:
    """构造 HTTP Authorization 头；scheme 来自 MCP_AUTH_SCHEME。"""
    resolved = resolve_auth_token(token)
    if not resolved:
        return None
    scheme = auth_scheme()
    if not scheme:
        return resolved
    return f"{scheme} {resolved}"


def build_auth_meta(token: str | None) -> dict[str, Any] | None:
    """构造 MCP call_tool 的 _meta 字段（不暴露给 LLM）。"""
    resolved = resolve_auth_token(token)
    if not resolved:
        return None
    return {AUTH_META_KEY: {"token": resolved}}


def extract_token_from_meta(meta: Any) -> str | None:
    """从 MCP 请求的 _meta 中解析用户 token。"""
    if meta is None:
        return None

    if hasattr(meta, "model_dump"):
        data = meta.model_dump(by_alias=True, exclude_none=True)
    elif isinstance(meta, dict):
        data = meta
    else:
        return None

    block = data.get(AUTH_META_KEY)
    if not isinstance(block, dict):
        return None

    raw = block.get("token")
    if isinstance(raw, str) and raw.strip():
        return raw.strip()
    return None


def set_request_auth_token(token: str | None) -> contextvars.Token:
    return _request_auth_token.set(resolve_auth_token(token))


def reset_request_auth_token(ctx: contextvars.Token) -> None:
    _request_auth_token.reset(ctx)


def get_request_auth_token() -> str | None:
    return _request_auth_token.get()


class AuthPassthroughMiddleware(Middleware):
    """FastMCP 中间件：从 tools/call 的 _meta 提取 token 写入请求上下文。"""

    async def on_call_tool(
        self,
        context: MiddlewareContext[mt.CallToolRequestParams],
        call_next: CallNext[mt.CallToolRequestParams, Any],
    ) -> Any:
        token = extract_token_from_meta(getattr(context.message, "meta", None))
        ctx = set_request_auth_token(token)
        try:
            return await call_next(context)
        finally:
            reset_request_auth_token(ctx)
