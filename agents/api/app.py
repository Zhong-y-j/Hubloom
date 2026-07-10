"""Hubloom HTTP API（FastAPI）。"""

from __future__ import annotations

import asyncio
import os
from contextlib import asynccontextmanager
from pathlib import Path
from typing import AsyncIterator

from fastapi import FastAPI, Header, HTTPException, Query
from fastapi.responses import FileResponse, JSONResponse, Response, StreamingResponse
from starlette.staticfiles import StaticFiles

from agents.api.client_headers import ClientHeaderContext, parse_client_headers
from agents.api.request_context import clear_request_context, set_request_context
from agents.api.events import event_to_sse, format_sse, turn_complete_payload
from agents.api.history import ChatHistoryResponse, messages_for_display
from agents.api.schemas import (
    ApplyConfigRequest,
    ApplyConfigResponse,
    ChatRequest,
    ChatResponse,
)
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
from agents.agent_log import cortex_log
from agents.events import ErrorEvent
from memory.store.conversation_sqlite_store import ConversationSQLitesStore
from observability import setup_log

_runtime: CortexRuntime | None = None
_agent_lock = asyncio.Lock()
_STATIC_DIR = Path(__file__).resolve().parent / "static"
_NO_CACHE = "no-cache, no-store, must-revalidate"
_RUNTIME_CONFIG_KEYS = (
    "OPENAI_MODEL",
    "OPENAI_BASE_URL",
    "MCP_SWAGGER_URL",
    "MCP_BASE_URL",
    "MCP_AUTH_SCHEME",
)
_DEFAULT_SWAGGER_URL = "https://petstore.swagger.io/v2/swagger.json"


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


def _apply_client_context(ctx: ClientHeaderContext, *, session_id: str) -> None:
    set_request_context(session_id=session_id, **ctx)


def _clean_config_value(value: str | None) -> str | None:
    text = (value or "").strip()
    return text or None


def _env_value(key: str, default: str = "") -> str:
    return (os.getenv(key) or default).strip()


def _config_env_updates(config: ApplyConfigRequest) -> dict[str, str]:
    """Only non-secret runtime settings are applied to process env."""
    pairs = {
        "OPENAI_MODEL": config.openai_model,
        "OPENAI_BASE_URL": config.openai_base_url,
        "MCP_SWAGGER_URL": config.mcp_swagger_url,
        "MCP_BASE_URL": config.mcp_base_url,
        "MCP_AUTH_SCHEME": config.mcp_auth_scheme,
    }
    return {
        key: value
        for key, raw in pairs.items()
        if (value := _clean_config_value(raw)) is not None
    }


def _restore_env(snapshot: dict[str, str | None]) -> None:
    for key, value in snapshot.items():
        if value is None:
            os.environ.pop(key, None)
        else:
            os.environ[key] = value


def _public_base_url() -> str:
    """对外公布的 A2A / Card URL（勿用 0.0.0.0）。"""
    explicit = (os.getenv("CORTEX_PUBLIC_URL") or "").strip().rstrip("/")
    if explicit:
        return explicit
    port = int(os.getenv("CORTEX_API_PORT", "8000"))
    return f"http://127.0.0.1:{port}"


async def _mount_a2a_routes(app: FastAPI) -> None:
    """把 A2A Card + JSON-RPC 挂到主 FastAPI（与 Chat 同进程）。"""
    from a2a_adapter.server.app import build_a2a_routes
    from agents.a2a.bridge import run_a2a_turn
    from agents.a2a.card import build_agent_card
    from mcp_adapter.gateway.catalog import load_catalog

    public_url = _public_base_url()
    catalog = await load_catalog()
    card = await build_agent_card(public_url, catalog)

    async def run_turn(query: str, task_id: str, on_stream) -> str:
        # 始终用当前全局 runtime（/v1/config/apply 重建后仍有效）
        runtime = _runtime
        if runtime is None:
            raise RuntimeError("CortexRuntime 尚未就绪")
        return await run_a2a_turn(
            runtime,
            query,
            task_id=task_id,
            on_stream=on_stream,
        )

    for route in build_a2a_routes(card, run_turn=run_turn, rpc_url="/"):
        app.router.routes.append(route)

    cortex_log(
        "a2a mounted on FastAPI",
        public_url=public_url,
        skill_count=len(card.skills),
        card=f"{public_url}/.well-known/agent-card.json",
    )


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
    global _runtime
    setup_log()
    _runtime = await build_runtime_async()
    await _mount_a2a_routes(_app)
    try:
        yield
    finally:
        if _runtime is not None:
            await _runtime.close()
        _runtime = None


app = FastAPI(
    title="Hubloom API",
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


@app.post("/v1/config/apply", response_model=ApplyConfigResponse)
async def apply_client_config(config: ApplyConfigRequest) -> ApplyConfigResponse:
    """应用前端体验配置，并重建 MCP runtime 以加载新的 Swagger。"""
    global _runtime

    async with _agent_lock:
        updates = _config_env_updates(config)
        snapshot = {key: os.environ.get(key) for key in _RUNTIME_CONFIG_KEYS}
        os.environ.update(updates)

        swagger_url = _env_value("MCP_SWAGGER_URL", _DEFAULT_SWAGGER_URL)
        base_url = _env_value("MCP_BASE_URL")

        try:
            from mcp_adapter.gateway.catalog import build_catalog_from_openapi
            from mcp_adapter.spec.filter import count_operations
            from mcp_adapter.spec.pipeline import prepare_openapi

            openapi, resolved_base_url = await prepare_openapi(
                swagger_url,
                base_url=base_url or None,
            )
            catalog = build_catalog_from_openapi(openapi)
            new_runtime = await build_runtime_async()
            if new_runtime.mcp_bindings is None:
                await new_runtime.close()
                raise RuntimeError("MCP 网关启动失败，请检查 Swagger / Base URL")
        except Exception as exc:
            _restore_env(snapshot)
            raise HTTPException(
                status_code=400,
                detail=f"连接 Swagger 失败：{exc}",
            ) from exc

        old_runtime = _runtime
        _runtime = new_runtime
        if old_runtime is not None:
            await old_runtime.close()

        return ApplyConfigResponse(
            status="ok",
            swagger_url=swagger_url,
            base_url=resolved_base_url,
            group_count=len(catalog.groups),
            tool_count=count_operations(openapi),
        )


@app.post("/v1/chat")
async def chat(
    body: ChatRequest,
    authorization: str | None = Header(default=None),
    x_session_id: str | None = Header(default=None, alias="X-Session-Id"),
    x_openai_api_key: str | None = Header(default=None, alias="X-OpenAI-Api-Key"),
    x_openai_model: str | None = Header(default=None, alias="X-OpenAI-Model"),
    x_openai_base_url: str | None = Header(default=None, alias="X-OpenAI-Base-Url"),
    x_mcp_token: str | None = Header(default=None, alias="X-MCP-Token"),
    x_mcp_auth_scheme: str | None = Header(default=None, alias="X-MCP-Auth-Scheme"),
    x_mcp_swagger_url: str | None = Header(default=None, alias="X-MCP-Swagger-Url"),
    x_mcp_base_url: str | None = Header(default=None, alias="X-MCP-Base-Url"),
):
    if _runtime is None:
        raise HTTPException(status_code=503, detail="运行时尚未初始化")

    message = body.message.strip()
    if not message:
        raise HTTPException(status_code=400, detail="message 不能为空")

    raw_key = _raw_session_key(body.session_id, x_session_id)
    session_id = format_session_id(raw_key)
    client_ctx = parse_client_headers(
        authorization=authorization,
        x_openai_api_key=x_openai_api_key,
        x_openai_model=x_openai_model,
        x_openai_base_url=x_openai_base_url,
        x_mcp_token=x_mcp_token,
        x_mcp_auth_scheme=x_mcp_auth_scheme,
        x_mcp_swagger_url=x_mcp_swagger_url,
        x_mcp_base_url=x_mcp_base_url,
    )
    if not client_ctx["openai_api_key"]:
        raise HTTPException(
            status_code=400,
            detail="请在前端填写 OPENAI_API_KEY，或在服务端配置环境变量",
        )
    cortex_log(
        "chat client auth",
        has_bearer=bool(client_ctx["bearer_token"]),
        scheme=client_ctx["mcp_auth_scheme"],
    )

    if body.stream:
        return StreamingResponse(
            _stream_chat(
                message,
                session_key=raw_key or "tester_id",
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
        session_key=raw_key or "tester_id",
        session_id=session_id,
        client_ctx=client_ctx,
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
    client_ctx: ClientHeaderContext,
) -> AsyncIterator[str]:
    async with _agent_lock:
        _apply_client_context(client_ctx, session_id=session_id)
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
    client_ctx: ClientHeaderContext,
) -> ChatResponse:
    async with _agent_lock:
        _apply_client_context(client_ctx, session_id=session_id)
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
