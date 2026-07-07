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

from agents.api.request_context import clear_request_context, set_request_context
from agents.api.events import event_to_sse, format_sse, turn_complete_payload
from agents.api.history import ChatHistoryResponse, messages_for_display
from agents.api.schemas import ChatRequest, ChatResponse
from agents.app.bootstrap import CortexRuntime, build_runtime_async
from agents.app.session import (
    DEFAULT_MEMORY_DB,
    DEFAULT_SESSION_ID,
    ENABLE_LONG_TERM_MEMORY,
    ENABLE_RAG,
    RAG_DOCS_RAW,
    SESSION_ID_TEMPLATE,
    format_session_id,
)
from agents.adp.cortex_agent import CortexAgent
from agents.events import ErrorEvent
from memory.store.conversation_sqlite_store import ConversationSQLitesStore
from observability import setup_log

_runtime: CortexRuntime | None = None
_agent_lock = asyncio.Lock()
_STATIC_DIR = Path(__file__).resolve().parent / "static"
_NO_CACHE = "no-cache, no-store, must-revalidate"


class NoCacheStaticFiles(StaticFiles):
    """开发态静态资源禁用强缓存，避免前端改动不生效。"""

    async def get_response(self, path: str, scope):  # type: ignore[override]
        response: Response = await super().get_response(path, scope)
        response.headers["Cache-Control"] = _NO_CACHE
        response.headers["Pragma"] = "no-cache"
        return response


def _raw_session_key(body_session: str | None, header_session: str | None) -> str:
    for value in (body_session, header_session):
        if value and value.strip():
            return value.strip()
    return ""


def _resolve_session_id(body_session: str | None, header_session: str | None) -> str:
    return format_session_id(_raw_session_key(body_session, header_session))


def _extract_bearer(authorization: str | None) -> str | None:
    if not authorization:
        return None
    text = authorization.strip()
    if text.lower().startswith("bearer "):
        token = text[7:].strip()
        return token or None
    return text or None


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
    global _runtime
    setup_log()
    _runtime = await build_runtime_async()
    try:
        yield
    finally:
        if _runtime is not None:
            await _runtime.close()
        _runtime = None


app = FastAPI(
    title="Agent Cortex API",
    description="ADP 编排（Assessor → Chat / Thought）HTTP 接口",
    version="0.2.0",
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
    if _runtime is None:
        raise HTTPException(status_code=503, detail="运行时尚未初始化")

    message = body.message.strip()
    if not message:
        raise HTTPException(status_code=400, detail="message 不能为空")

    raw_key = _raw_session_key(body.session_id, x_session_id)
    session_id = format_session_id(raw_key)
    bearer = _extract_bearer(authorization)

    if body.stream:
        return StreamingResponse(
            _stream_chat(
                message,
                session_key=raw_key or "tester_id",
                session_id=session_id,
                bearer=bearer,
            ),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                "X-Accel-Buffering": "no",
            },
        )

    result = await _run_chat_once(
        message,
        session_key=raw_key or "tester_id",
        session_id=session_id,
        bearer=bearer,
    )
    return JSONResponse(content=result.model_dump())


@app.get("/v1/chat/history", response_model=ChatHistoryResponse)
async def chat_history(
    session_id: str | None = Query(
        default=None, description="裸 user_id 或完整 namespace"
    ),
    authorization: str | None = Header(default=None),
    x_session_id: str | None = Header(default=None, alias="X-Session-Id"),
) -> ChatHistoryResponse:
    if _runtime is None:
        raise HTTPException(status_code=503, detail="运行时尚未初始化")

    resolved = _resolve_session_id(session_id, x_session_id)
    db_path = _runtime.memory_db_path if _runtime else DEFAULT_MEMORY_DB
    store = ConversationSQLitesStore(db_path)
    try:
        rows = await asyncio.to_thread(store.get_chat_history, resolved)
    finally:
        store.close()

    messages = messages_for_display(rows)
    return ChatHistoryResponse(
        session_id=resolved,
        messages=messages,
        total=len(messages),
    )


async def _stream_chat(
    message: str,
    *,
    session_key: str,
    session_id: str,
    bearer: str | None,
) -> AsyncIterator[str]:
    async with _agent_lock:
        set_request_context(bearer_token=bearer, session_id=session_id)
        runtime = _runtime
        assert runtime is not None
        agent = runtime.create_agent(session_key)
        try:
            async for ev in agent.run_stream(message):
                mapped = event_to_sse(ev)
                if mapped is not None:
                    name, payload = mapped
                    payload["session_id"] = session_id
                    yield format_sse(name, payload)
                if isinstance(ev, ErrorEvent):
                    return

            outcome = agent.get_last_outcome()
            if outcome is not None:
                name, payload = turn_complete_payload(
                    route=outcome.route.value,
                    final_message=(outcome.final_answer or "").strip(),
                    session_id=session_id,
                    reason=outcome.assess.reason,
                )
                yield format_sse(name, payload)
        except Exception as exc:
            yield format_sse("error", {"error": str(exc), "session_id": session_id})
        finally:
            clear_request_context()


async def _run_chat_once(
    message: str,
    *,
    session_key: str,
    session_id: str,
    bearer: str | None,
) -> ChatResponse:
    async with _agent_lock:
        set_request_context(bearer_token=bearer, session_id=session_id)
        runtime = _runtime
        assert runtime is not None
        agent: CortexAgent = runtime.create_agent(session_key)
        try:
            async for ev in agent.run_stream(message):
                if isinstance(ev, ErrorEvent):
                    raise HTTPException(status_code=500, detail=ev.error)
        finally:
            clear_request_context()

    outcome = agent.get_last_outcome()
    if outcome is None:
        raise HTTPException(status_code=500, detail="未收到编排结果")

    return ChatResponse(
        route=outcome.route.value,
        final_message=(outcome.final_answer or "").strip(),
        session_id=session_id,
        reason=outcome.assess.reason,
    )


def main() -> None:
    import uvicorn

    host = os.getenv("CORTEX_API_HOST", "0.0.0.0")
    port = int(os.getenv("CORTEX_API_PORT", "8000"))
    uvicorn.run(
        "agents.api.app:app",
        host=host,
        port=port,
        reload=os.getenv("CORTEX_API_RELOAD", "").lower() in ("1", "true", "yes"),
    )


if __name__ == "__main__":
    main()
