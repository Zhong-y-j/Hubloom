"""在 MCP Server 侧捕获每次 HTTP 响应的状态（供工具结果封装）。"""

from __future__ import annotations

import contextvars
from typing import Any

import httpx

_last_http_response: contextvars.ContextVar[httpx.Response | None] = contextvars.ContextVar(
    "_last_http_response", default=None
)


def get_last_http_response() -> httpx.Response | None:
    return _last_http_response.get()


class StatusCapturingClient(httpx.AsyncClient):
    """httpx 客户端：每次 send 后记录 Response 到 contextvar。"""

    async def send(self, request: httpx.Request, *args: Any, **kwargs: Any) -> httpx.Response:
        response = await super().send(request, *args, **kwargs)
        _last_http_response.set(response)
        return response
