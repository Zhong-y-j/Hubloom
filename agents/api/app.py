"""Agent Cortex HTTP API（FastAPI）。"""

from __future__ import annotations

import asyncio
import os
from contextlib import asynccontextmanager
from pathlib import Path
from typing import AsyncIterator

from fastapi import FastAPI, Header, HTTPException, Query
from fastapi.responses import FileResponse, JSONResponse, Response, StreamingResponse
from starlette.staticfiles import StaticFiles

from agents.api.context import clear_request_context, set_request_context
from agents.api.events import event_to_sse, format_sse
from agents.api.history import ChatHistoryResponse, messages_for_display
from agents.api.schemas import ChatRequest, ChatResponse
from agents.app.bootstrap import (
    DEFAULT_SESSION_ID,
    ENABLE_LONG_TERM_MEMORY,
    ENABLE_RAG,
    RAG_DOCS_RAW,
    SESSION_ID_TEMPLATE,
    build_hub_async,
    format_session_id,
)
from agents.core.events import ErrorEvent, HubTurnCompleteEvent
from agents.hub import CortexHub
from observability import setup_log

_hub: CortexHub | None = None
_hub_lock = asyncio.Lock()
_STATIC_DIR = Path(__file__).resolve().parent / "static"
_NO_CACHE = "no-cache, no-store, must-revalidate"


class NoCacheStaticFiles(StaticFiles):
    """开发态静态资源禁用强缓存，避免前端改动不生效。"""

    async def get_response(self, path: str, scope):  # type: ignore[override]
        response: Response = await super().get_response(path, scope)
        response.headers["Cache-Control"] = _NO_CACHE
        response.headers["Pragma"] = "no-cache"
        return response


def _resolve_session_id(body_session: str | None, header_session: str | None) -> str:
    for value in (body_session, header_session):
        if value and value.strip():
            return format_session_id(value)
    return DEFAULT_SESSION_ID


def _extract_bearer(authorization: str | None) -> str | None:
    if not authorization:
        return None
    text = authorization.strip()
    if text.lower().startswith("bearer "):
        token = text[7:].strip()
        return token or None
    return text or None


def _bind_hub_session(hub: CortexHub, session_id: str) -> None:
    """对话与长期记忆 namespace 对齐到同一 session_id，方便记忆召回。"""
    hub.react._session_id = session_id  # noqa: SLF001 — API 按请求切换会话
    if hub.react.memory is not None:
        hub.react.memory.bind_namespace(session_id)


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
    global _hub
    setup_log()
    _hub = await build_hub_async()
    try:
        yield
    finally:
        if _hub is not None:
            await _hub.close()
        _hub = None


app = FastAPI(
    title="Agent Cortex API",
    description="OpenAPI/MCP 驱动的对话 Agent HTTP 接口",
    version="0.1.0",
    lifespan=lifespan,
)

if _STATIC_DIR.is_dir():
    app.mount("/static", NoCacheStaticFiles(directory=_STATIC_DIR), name="static")


@app.get("/")
async def chat_page() -> FileResponse:
    index = _STATIC_DIR / "index.html"
    if not index.is_file():
        raise HTTPException(status_code=404, detail="前端页面未找到")
    return FileResponse(
        index,
        headers={"Cache-Control": _NO_CACHE, "Pragma": "no-cache"},
    )


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/v1/config")
async def client_config() -> dict[str, str | bool]:
    return {
        "default_session_id": DEFAULT_SESSION_ID,
        "session_id_template": SESSION_ID_TEMPLATE,
        "enable_long_term_memory": ENABLE_LONG_TERM_MEMORY,
        "enable_rag": ENABLE_RAG,
        "rag_docs": RAG_DOCS_RAW,
    }


@app.post("/v1/chat")
async def chat(
    body: ChatRequest,
    authorization: str | None = Header(default=None),
    x_session_id: str | None = Header(default=None, alias="X-Session-Id"),
):
    if _hub is None:
        raise HTTPException(status_code=503, detail="Hub 尚未初始化")

    message = body.message.strip()
    if not message:
        raise HTTPException(status_code=400, detail="message 不能为空")

    session_id = _resolve_session_id(body.session_id, x_session_id)
    bearer = _extract_bearer(authorization)

    if body.stream:
        return StreamingResponse(
            _stream_chat(message, session_id=session_id, bearer=bearer),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                "X-Accel-Buffering": "no",
            },
        )

    result = await _run_chat_once(message, session_id=session_id, bearer=bearer)
    return JSONResponse(content=result.model_dump())


@app.get("/v1/chat/history", response_model=ChatHistoryResponse)
async def chat_history(
    session_id: str | None = Query(
        default=None, description="裸 user_id 或完整 namespace"
    ),
    authorization: str | None = Header(default=None),
    x_session_id: str | None = Header(default=None, alias="X-Session-Id"),
) -> ChatHistoryResponse:
    if _hub is None:
        raise HTTPException(status_code=503, detail="Hub 尚未初始化")

    resolved = _resolve_session_id(session_id, x_session_id)
    store = _hub.react._conversation_store  # noqa: SLF001
    if store is None:
        return ChatHistoryResponse(session_id=resolved, messages=[], total=0)

    rows = await asyncio.to_thread(store.get_chat_history, resolved)
    messages = messages_for_display(rows)
    return ChatHistoryResponse(
        session_id=resolved,
        messages=messages,
        total=len(messages),
    )


async def _stream_chat(
    message: str,
    *,
    session_id: str,
    bearer: str | None,
) -> AsyncIterator[str]:
    async with _hub_lock:
        set_request_context(bearer_token=bearer, session_id=session_id)
        hub = _hub
        assert hub is not None
        _bind_hub_session(hub, session_id)
        try:
            async for ev in hub.run_turn_stream(message):
                mapped = event_to_sse(ev)
                if mapped is not None:
                    name, payload = mapped
                    payload["session_id"] = session_id
                    yield format_sse(name, payload)
        except Exception as exc:
            yield format_sse("error", {"error": str(exc), "session_id": session_id})
        finally:
            clear_request_context()


async def _run_chat_once(
    message: str,
    *,
    session_id: str,
    bearer: str | None,
) -> ChatResponse:
    final: ChatResponse | None = None
    async with _hub_lock:
        set_request_context(bearer_token=bearer, session_id=session_id)
        hub = _hub
        assert hub is not None
        _bind_hub_session(hub, session_id)
        try:
            async for ev in hub.run_turn_stream(message):
                if isinstance(ev, HubTurnCompleteEvent):
                    text = (ev.final_user_message or ev.user_reply or "").strip()
                    final = ChatResponse(
                        route=ev.route,
                        final_message=text,
                        user_reply=ev.user_reply,
                        session_id=session_id,
                        intent=(ev.intent.to_dict() if ev.intent is not None else None),
                        deliverable=ev.deliverable,
                        delivery_summary=ev.delivery_summary,
                    )
                elif isinstance(ev, ErrorEvent):
                    raise HTTPException(status_code=500, detail=ev.error)
        finally:
            clear_request_context()

    if final is None:
        outcome = hub.get_last_outcome()
        if outcome is not None:
            text = (outcome.final_user_message or outcome.user_reply or "").strip()
            return ChatResponse(
                route=outcome.route,
                final_message=text,
                user_reply=outcome.user_reply,
                session_id=session_id,
                intent=(
                    outcome.intent.to_dict() if outcome.intent is not None else None
                ),
                deliverable=outcome.deliverable,
                delivery_summary=outcome.delivery_summary,
            )
        raise HTTPException(status_code=500, detail="未收到 HubTurnCompleteEvent")

    return final


def main() -> None:
    import uvicorn

    host = os.getenv("CORTEX_API_HOST", "0.0.0.0")
    port = int(os.getenv("CORTEX_API_PORT", "8080"))
    uvicorn.run(
        "agents.api.app:app",
        host=host,
        port=port,
        reload=os.getenv("CORTEX_API_RELOAD", "").lower() in ("1", "true", "yes"),
    )


if __name__ == "__main__":
    main()
