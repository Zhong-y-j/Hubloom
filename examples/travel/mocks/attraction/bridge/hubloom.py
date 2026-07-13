"""Forward attraction demo UI requests to Hubloom (BFF / proxy)."""

from __future__ import annotations

import os
from typing import AsyncIterator

import httpx
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse, Response, StreamingResponse

HUBLOOM_BASE_URL = os.getenv("HUBLOOM_BASE_URL", "http://127.0.0.1:8004").rstrip("/")

FORWARD_HEADER_NAMES = frozenset(
    {
        "authorization",
        "x-session-id",
        "x-openai-api-key",
        "x-openai-model",
        "x-openai-base-url",
        "x-mcp-token",
        "x-mcp-auth-scheme",
        "x-mcp-swagger-url",
        "x-mcp-base-url",
    }
)

router = APIRouter(prefix="/hubloom", tags=["hubloom"])


def _forward_headers(request: Request) -> dict[str, str]:
    headers: dict[str, str] = {}
    for name, value in request.headers.items():
        if name.lower() in FORWARD_HEADER_NAMES:
            headers[name] = value
    return headers


def _error_detail(response: httpx.Response) -> str:
    try:
        payload = response.json()
    except Exception:
        return response.text or f"Hubloom HTTP {response.status_code}"
    detail = payload.get("detail")
    if isinstance(detail, str):
        return detail
    if detail is not None:
        return str(detail)
    return response.text or f"Hubloom HTTP {response.status_code}"


@router.post("/config/apply")
async def apply_config(request: Request) -> Response:
    """代理 Hubloom ``POST /v1/config/apply``，用于连接景点 Swagger。"""
    body = await request.body()
    headers = _forward_headers(request)
    headers["Content-Type"] = request.headers.get("content-type", "application/json")

    async with httpx.AsyncClient(timeout=120.0) as client:
        upstream = await client.post(
            f"{HUBLOOM_BASE_URL}/v1/config/apply",
            content=body,
            headers=headers,
        )

    if upstream.status_code >= 400:
        raise HTTPException(status_code=upstream.status_code, detail=_error_detail(upstream))

    return JSONResponse(content=upstream.json(), status_code=upstream.status_code)


@router.post("/chat")
async def chat(request: Request) -> StreamingResponse:
    """代理 Hubloom ``POST /v1/chat``，SSE 流式原样透传。"""
    body = await request.body()
    headers = _forward_headers(request)
    headers["Content-Type"] = request.headers.get("content-type", "application/json")

    client = httpx.AsyncClient(timeout=None)
    try:
        upstream_request = client.build_request(
            "POST",
            f"{HUBLOOM_BASE_URL}/v1/chat",
            content=body,
            headers=headers,
        )
        upstream = await client.send(upstream_request, stream=True)
    except httpx.RequestError as exc:
        await client.aclose()
        raise HTTPException(
            status_code=502,
            detail=f"无法连接 Hubloom（{HUBLOOM_BASE_URL}）：{exc}",
        ) from exc

    if upstream.status_code >= 400:
        error_body = await upstream.aread()
        await upstream.aclose()
        await client.aclose()
        detail = error_body.decode("utf-8", errors="replace") or f"Hubloom HTTP {upstream.status_code}"
        raise HTTPException(status_code=upstream.status_code, detail=detail)

    media_type = upstream.headers.get("content-type", "text/event-stream")

    async def stream() -> AsyncIterator[bytes]:
        try:
            async for chunk in upstream.aiter_bytes():
                yield chunk
        finally:
            await upstream.aclose()
            await client.aclose()

    return StreamingResponse(
        stream(),
        media_type=media_type,
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@router.get("/chat/history")
async def chat_history(request: Request) -> Response:
    """代理 Hubloom ``GET /v1/chat/history``。"""
    headers = _forward_headers(request)
    async with httpx.AsyncClient(timeout=60.0) as client:
        upstream = await client.get(
            f"{HUBLOOM_BASE_URL}/v1/chat/history",
            params=dict(request.query_params),
            headers=headers,
        )

    if upstream.status_code >= 400:
        raise HTTPException(status_code=upstream.status_code, detail=_error_detail(upstream))

    return JSONResponse(content=upstream.json(), status_code=upstream.status_code)
