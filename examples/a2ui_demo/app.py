"""A2UI Demo API：HubloomAgent 对话 + 场景实验室。

开发::

    # 终端 1 — 后端（接智能体）
    uv run python -m examples.a2ui_demo

    # 终端 2 — Vue（代理 /v1 → 本服务）
    cd examples/a2ui_demo/web && npm install && npm run dev

打开 http://127.0.0.1:5173/
"""

from __future__ import annotations

import asyncio
import os
from contextlib import asynccontextmanager
from pathlib import Path
from typing import AsyncIterator

from fastapi import FastAPI, Header, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles

from agents.agent_log import cortex_log
from agents.events import ErrorEvent
from agents.sse import event_to_sse, format_sse, turn_complete_payload
from examples.chat.client_headers import ClientHeaderContext, parse_client_headers
from examples.chat.history import ChatHistoryResponse, messages_for_display
from examples.chat.schemas import ChatRequest, ChatResponse, McpStatusResponse
from hubloom import HubloomAgent, HubloomConfig, HubloomSession
from hubloom.context import clear_request_context
from hubloom.runtime import CortexRuntime
from hubloom.session import (
    DEFAULT_MEMORY_DB,
    DEFAULT_SESSION_ID,
    ENABLE_LONG_TERM_MEMORY,
    ENABLE_RAG,
    RAG_DOCS_RAW,
    SESSION_ID_TEMPLATE,
    format_session_id,
)
from memory.store.conversation_sqlite_store import ConversationSQLitesStore
from observability import setup_log

from .samples import get_scenario, list_scenarios

_DIR = Path(__file__).resolve().parent
_WEB_DIST = _DIR / "web" / "dist"

_hubloom: HubloomAgent | None = None
_agent_lock = asyncio.Lock()


def _runtime() -> CortexRuntime | None:
    return None if _hubloom is None else _hubloom.runtime


def _raw_session_key(body_session: str | None, header_session: str | None) -> str:
    for value in (body_session, header_session):
        if value and value.strip():
            return value.strip()
    return ""


def _resolve_session_id(body_session: str | None, header_session: str | None) -> str:
    return format_session_id(_raw_session_key(body_session, header_session))


def _session_from_client(
    session_key: str,
    client_ctx: ClientHeaderContext,
) -> HubloomSession:
    if _hubloom is None:
        raise RuntimeError("HubloomAgent 尚未就绪")
    return _hubloom.session(session_key, token=client_ctx["bearer_token"])


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
    global _hubloom
    setup_log()
    _hubloom = await HubloomAgent.create(HubloomConfig.from_file("config/env.yaml"))
    try:
        yield
    finally:
        if _hubloom is not None:
            await _hubloom.close()
        _hubloom = None


app = FastAPI(
    title="Hubloom A2UI Demo",
    description="Agent 对话（SSE）+ A2UI 场景实验室",
    version="0.4.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://127.0.0.1:5173",
        "http://localhost:5173",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
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


@app.get("/v1/mcp/status", response_model=McpStatusResponse)
async def mcp_status() -> McpStatusResponse:
    if _hubloom is None:
        raise HTTPException(status_code=503, detail="运行时尚未初始化")

    runtime = _runtime()
    cfg = _hubloom.config
    swagger_url = (cfg.mcp_swagger_url or "").strip()
    base_url = (cfg.mcp_base_url or "").strip()
    mcp_ready = runtime is not None and runtime.mcp_bindings is not None

    group_count = 0
    tool_count = 0
    detail = ""
    if mcp_ready and swagger_url:
        try:
            from mcp_adapter.gateway.catalog import load_catalog
            from mcp_adapter.spec.filter import count_operations

            catalog = await load_catalog(
                swagger_url=swagger_url,
                base_url=base_url or None,
            )
            group_count = len(catalog.groups)
            tool_count = sum(len(g.tools) for g in catalog.groups.values())
            if tool_count == 0:
                from mcp_adapter.spec.pipeline import prepare_openapi

                openapi, resolved = await prepare_openapi(
                    swagger_url, base_url=base_url or None
                )
                tool_count = count_operations(openapi)
                if resolved:
                    base_url = resolved
        except Exception as exc:
            detail = f"MCP 已连接，但读取目录失败：{exc}"
    elif not mcp_ready:
        detail = "服务端 MCP 未就绪，请检查 config/env.yaml 中的 mcp.swagger_url"

    return McpStatusResponse(
        status="ok" if mcp_ready else "error",
        mcp_ready=mcp_ready,
        swagger_url=swagger_url,
        base_url=base_url,
        group_count=group_count,
        tool_count=tool_count,
        detail=detail,
    )


@app.post("/v1/chat")
async def chat(
    body: ChatRequest,
    authorization: str | None = Header(default=None),
    x_session_id: str | None = Header(default=None, alias="X-Session-Id"),
    x_mcp_token: str | None = Header(default=None, alias="X-MCP-Token"),
):
    if _hubloom is None:
        raise HTTPException(status_code=503, detail="运行时尚未初始化")

    message = body.message.strip()
    if not message:
        raise HTTPException(status_code=400, detail="message 不能为空")

    raw_key = _raw_session_key(body.session_id, x_session_id)
    session_id = format_session_id(raw_key)
    client_ctx = parse_client_headers(
        authorization=authorization,
        x_mcp_token=x_mcp_token,
    )
    if not client_ctx["bearer_token"]:
        raise HTTPException(
            status_code=400,
            detail="请在前端填写业务 Token（X-MCP-Token / Authorization）",
        )
    session_key = (raw_key or "").strip()
    if not session_key:
        raise HTTPException(status_code=400, detail="请填写用户 ID（session_id）")

    cortex_log(
        "a2ui_demo chat auth",
        has_bearer=True,
        session_key=session_key[:32],
    )

    if body.stream:
        return StreamingResponse(
            _stream_chat(
                message,
                session_key=session_key,
                session_id=session_id,
                client_ctx=client_ctx,
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
        session_key=session_key,
        session_id=session_id,
        client_ctx=client_ctx,
    )
    return JSONResponse(content=result.model_dump())


@app.get("/v1/chat/history", response_model=ChatHistoryResponse)
async def chat_history(
    session_id: str | None = Query(
        default=None, description="裸 user_id 或完整 namespace"
    ),
    x_session_id: str | None = Header(default=None, alias="X-Session-Id"),
) -> ChatHistoryResponse:
    if _hubloom is None:
        raise HTTPException(status_code=503, detail="运行时尚未初始化")

    resolved = _resolve_session_id(session_id, x_session_id)
    runtime = _runtime()
    db_path = runtime.memory_db_path if runtime else DEFAULT_MEMORY_DB
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


@app.get("/v1/scenarios")
async def scenarios() -> dict:
    return {"scenarios": list_scenarios()}


@app.get("/v1/scenarios/{scenario_id}")
async def scenario_detail(scenario_id: str) -> dict:
    try:
        return get_scenario(scenario_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=f"未知场景: {scenario_id}") from exc


async def _stream_chat(
    message: str,
    *,
    session_key: str,
    session_id: str,
    client_ctx: ClientHeaderContext,
) -> AsyncIterator[str]:
    async with _agent_lock:
        sess = _session_from_client(session_key, client_ctx)
        try:
            async for ev in sess.run_stream(message):
                mapped = event_to_sse(ev)
                if mapped is not None:
                    name, payload = mapped
                    payload["session_id"] = session_id
                    yield format_sse(name, payload)
                if isinstance(ev, ErrorEvent) and not ev.recoverable:
                    return

            outcome = sess.get_last_outcome()
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
    client_ctx: ClientHeaderContext,
) -> ChatResponse:
    async with _agent_lock:
        sess = _session_from_client(session_key, client_ctx)
        try:
            async for ev in sess.run_stream(message):
                if isinstance(ev, ErrorEvent) and not ev.recoverable:
                    raise HTTPException(status_code=500, detail=ev.error)
        finally:
            clear_request_context()

    outcome = sess.get_last_outcome()
    if outcome is None:
        raise HTTPException(status_code=500, detail="未收到编排结果")

    return ChatResponse(
        route=outcome.route.value,
        final_message=(outcome.final_answer or "").strip(),
        session_id=session_id,
        reason=outcome.assess.reason,
    )


if (_WEB_DIST / "index.html").is_file():
    _assets = _WEB_DIST / "assets"
    if _assets.is_dir():
        app.mount("/assets", StaticFiles(directory=_assets), name="assets")

    @app.get("/")
    async def index() -> FileResponse:
        return FileResponse(_WEB_DIST / "index.html")
else:

    @app.get("/")
    async def index_dev_hint() -> dict[str, str]:
        return {
            "message": "开发请运行 Vue: cd examples/a2ui_demo/web && npm run dev",
            "api": "/v1/chat",
            "health": "/health",
        }


def main() -> None:
    import uvicorn

    host = os.getenv("A2UI_DEMO_HOST", "127.0.0.1")
    port = int(os.getenv("A2UI_DEMO_PORT", "8010"))
    uvicorn.run(
        "examples.a2ui_demo.app:app",
        host=host,
        port=port,
        reload=os.getenv("A2UI_DEMO_RELOAD", "").lower() in ("1", "true", "yes"),
    )


if __name__ == "__main__":
    main()
