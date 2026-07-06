"""Worker 侧 httpx 客户端：按请求注入 Authorization。"""

from __future__ import annotations

import contextvars
from typing import Any

import httpx

from mcp_adapter.auth import build_authorization_header, get_request_auth_token

_last_http_response: contextvars.ContextVar[httpx.Response | None] = contextvars.ContextVar(
    "_last_http_response",
    default=None,
)


def get_last_http_response() -> httpx.Response | None:
    return _last_http_response.get()


class AuthedHttpClient(httpx.AsyncClient):
    """按 MCP 请求上下文为下游 REST 调用附加 Authorization。"""

    async def send(
        self,
        request: httpx.Request,
        *args: Any,
        **kwargs: Any,
    ) -> httpx.Response:
        header = build_authorization_header(get_request_auth_token())
        if header and "authorization" not in {k.lower() for k in request.headers}:
            request.headers["Authorization"] = header
        response = await super().send(request, *args, **kwargs)
        _last_http_response.set(response)
        return response
