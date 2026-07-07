"""Worker 侧 httpx 客户端：按请求注入 Authorization。"""

from __future__ import annotations

import contextvars
from typing import Any

import httpx

from mcp_adapter.auth import (
    auth_trace,
    build_authorization_header,
    get_request_auth_scheme,
    get_request_auth_token,
)

_last_http_response: contextvars.ContextVar[httpx.Response | None] = (
    contextvars.ContextVar(
        "_last_http_response",
        default=None,
    )
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
        token = get_request_auth_token()
        scheme = get_request_auth_scheme()
        header = build_authorization_header(token, scheme=scheme)
        auth_trace(
            "worker_http",
            method=request.method,
            url=str(request.url),
            has_token=bool(token),
            scheme=scheme,
            header=header,
        )
        if header and "authorization" not in {k.lower() for k in request.headers}:
            request.headers["Authorization"] = header
        response = await super().send(request, *args, **kwargs)
        _last_http_response.set(response)
        # print(f"[HTTP] {request.method} {request.url}", file=sys.stderr)
        # print(f"[HTTP] status={response.status_code}", file=sys.stderr)
        # print(f"[HTTP] body={response.text}", file=sys.stderr)
        return response
