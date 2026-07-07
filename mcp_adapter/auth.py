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
_request_auth_scheme: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "mcp_request_auth_scheme",
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


def resolve_auth_scheme(scheme: str | None = None) -> str:
    explicit = (scheme or "").strip()
    if explicit:
        return explicit
    ctx = (_request_auth_scheme.get() or "").strip()
    if ctx:
        return ctx
    return auth_scheme()


def build_authorization_header(
    token: str | None,
    *,
    scheme: str | None = None,
) -> str | None:
    """构造 HTTP Authorization 头。"""
    resolved = resolve_auth_token(token)
    if not resolved:
        return None
    prefix = resolve_auth_scheme(scheme)
    if not prefix:
        return resolved
    return f"{prefix} {resolved}"


def build_auth_meta(
    token: str | None,
    *,
    scheme: str | None = None,
) -> dict[str, Any] | None:
    """构造 MCP call_tool 的 _meta 字段（不暴露给 LLM）。"""
    resolved = resolve_auth_token(token)
    if not resolved:
        return None
    block: dict[str, Any] = {"token": resolved}
    prefix = (scheme or "").strip() or (_request_auth_scheme.get() or "").strip()
    if prefix:
        block["scheme"] = prefix
    return {AUTH_META_KEY: block}


def extract_auth_from_meta(meta: Any) -> tuple[str | None, str | None]:
    """从 MCP 请求的 _meta 中解析 token 与 scheme。"""
    if meta is None:
        return None, None

    if hasattr(meta, "model_dump"):
        data = meta.model_dump(by_alias=True, exclude_none=True)
    elif isinstance(meta, dict):
        data = meta
    else:
        return None, None

    block = data.get(AUTH_META_KEY)
    if not isinstance(block, dict):
        return None, None

    token: str | None = None
    raw = block.get("token")
    if isinstance(raw, str) and raw.strip():
        token = raw.strip()

    scheme: str | None = None
    raw_scheme = block.get("scheme")
    if isinstance(raw_scheme, str) and raw_scheme.strip():
        scheme = raw_scheme.strip()

    return token, scheme


def extract_token_from_meta(meta: Any) -> str | None:
    token, _ = extract_auth_from_meta(meta)
    return token


def extract_auth_from_middleware_context(
    context: MiddlewareContext[Any],
) -> tuple[str | None, str | None, str]:
    """从 FastMCP 中间件上下文解析鉴权信息。

    FastMCP 在 stdio 下不会把客户端 _meta 填到 ``context.message.meta``，
    实际挂在 ``context.fastmcp_context.request_context.meta``。
    """
    token, scheme = extract_auth_from_meta(getattr(context.message, "meta", None))
    if token:
        return token, scheme, "message.meta"

    fastmcp_ctx = context.fastmcp_context
    if fastmcp_ctx is not None:
        request_context = getattr(fastmcp_ctx, "request_context", None)
        if request_context is not None:
            token, scheme = extract_auth_from_meta(
                getattr(request_context, "meta", None)
            )
            if token:
                return token, scheme, "request_context.meta"

    return None, scheme, "none"


def set_request_auth(
    token: str | None,
    scheme: str | None = None,
) -> tuple[contextvars.Token, contextvars.Token]:
    token_ctx = _request_auth_token.set(resolve_auth_token(token))
    scheme_ctx = _request_auth_scheme.set((scheme or "").strip() or None)
    return token_ctx, scheme_ctx


def set_request_auth_token(token: str | None) -> contextvars.Token:
    return _request_auth_token.set(resolve_auth_token(token))


def reset_request_auth(
    token_ctx: contextvars.Token,
    scheme_ctx: contextvars.Token,
) -> None:
    _request_auth_token.reset(token_ctx)
    _request_auth_scheme.reset(scheme_ctx)


def reset_request_auth_token(ctx: contextvars.Token) -> None:
    _request_auth_token.reset(ctx)


def get_request_auth_token() -> str | None:
    return _request_auth_token.get()


def get_request_auth_scheme() -> str | None:
    return _request_auth_scheme.get()


def auth_trace(stage: str, /, **fields: Any) -> None:
    """鉴权透传诊断（CORTEX_AUTH_TRACE=1 或 CORTEX_MCP_LOG=1 时写入 debug.log）。"""
    try:
        from mcp_adapter.log import mcp_log

        mcp_log(f"auth {stage}", **fields)
    except ModuleNotFoundError:
        pass


class AuthPassthroughMiddleware(Middleware):
    """FastMCP 中间件：从 tools/call 的 _meta 提取 token 写入请求上下文。"""

    async def on_call_tool(
        self,
        context: MiddlewareContext[mt.CallToolRequestParams],
        call_next: CallNext[mt.CallToolRequestParams, Any],
    ) -> Any:
        tool = getattr(context.message, "name", "?")
        token, scheme, meta_source = extract_auth_from_middleware_context(context)
        auth_trace(
            "middleware",
            tool=tool,
            has_token=bool(token),
            scheme=scheme or auth_scheme(),
            meta_source=meta_source,
        )
        token_ctx, scheme_ctx = set_request_auth(token, scheme)
        try:
            result = await call_next(context)
            # import sys

            # tool = getattr(context.message, "name", "?")
            # print(
            #     f"[WORKER-MCP] tool={tool} isError={getattr(result, 'isError', None)}",
            #     file=sys.stderr,
            # )
            # for block in getattr(result, "content", None) or []:
            #     print(
            #         f"[WORKER-MCP] content={getattr(block, 'text', block)}",
            #         file=sys.stderr,
            #     )
            return result

        finally:
            reset_request_auth(token_ctx, scheme_ctx)
