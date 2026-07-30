"""Hubloom FastAPI 应用：Typed ReAct 产品 API。"""

from __future__ import annotations

import asyncio
import json
import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from fastapi import FastAPI, Header, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, StreamingResponse

from agent.run import RunResult
from core.models import Message, Role
from memory.store.conversation_sqlite_store import ConversationSQLitesStore
from observability import setup_log
from runtime import HubloomRuntime
from server.schemas import (
    ChatHistoryResponse,
    ChatRequest,
    ChatSyncResponse,
    HistoryMessage,
    McpStatusResponse,
    ResumeRequest,
)
from server.sse import event_to_sse, format_sse

_runtime: HubloomRuntime | None = None
_run_lock = asyncio.Lock()


def _resolve_session_id(
    body_session: str | None,
    header_session: str | None,
) -> str:
    return (body_session or header_session or "").strip()


def _bearer_from_headers(
    authorization: str | None,
    x_mcp_token: str | None,
) -> str | None:
    token = (x_mcp_token or "").strip()
    if token:
        return token
    auth = (authorization or "").strip()
    if auth.lower().startswith("bearer "):
        return auth[7:].strip() or None
    return auth or None


def _result_to_sync(session_id: str, result: RunResult) -> ChatSyncResponse:
    pending = None
    if result.pending is not None:
        pending = {
            "kind": result.pending.kind,
            "prompt": result.pending.prompt,
            "slots": result.pending.slots,
            "intent": result.pending.intent,
            "from_run_id": result.pending.from_run_id,
        }
    return ChatSyncResponse(
        session_id=session_id,
        status=result.status,
        content=result.content,
        ok=result.ok,
        error=result.error,
        journal_run_id=result.journal_run_id,
        evidence_ids=list(result.evidence_ids),
        await_token=result.await_token,
        wait_profile=result.wait_profile,
        pending=pending,
        think_rounds=result.think_rounds,
        tool_calls=result.tool_calls,
        elapsed_ms=result.elapsed_ms,
    )


def _history_messages(rows: list[dict[str, Any]]) -> list[HistoryMessage]:
    out: list[HistoryMessage] = []
    for row in rows:
        role = str(row.get("role") or "").strip()
        if role not in ("user", "assistant"):
            continue
        content = str(row.get("content") or "")
        meta_raw = row.get("metadata_json") or row.get("metadata")
        source = row.get("source")
        if isinstance(meta_raw, str) and meta_raw.strip():
            try:
                meta = json.loads(meta_raw)
                if isinstance(meta, dict) and meta.get("source"):
                    source = meta.get("source")
            except json.JSONDecodeError:
                pass
        out.append(
            HistoryMessage(
                role=role,  # type: ignore[arg-type]
                content=content,
                created_at=row.get("created_at"),
                source=str(source) if source else None,
            )
        )
    return out


def create_app(
    *,
    config_path: str | Path | None = None,
    runtime: HubloomRuntime | None = None,
) -> FastAPI:
    """构造 Hubloom Serve 应用。

    - 生产：传 ``config_path``，lifespan 内 ``from_config_file``
    - 单测：直接传入已装配的 ``runtime``（不读配置、不碰真 LLM）
    """
    cfg_path = Path(config_path).resolve() if config_path else None
    injected = runtime

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        global _runtime
        del app
        setup_log()
        if injected is not None:
            _runtime = injected
        else:
            if cfg_path is None or not cfg_path.is_file():
                raise FileNotFoundError(
                    f"配置文件不存在: {cfg_path}"
                )
            _runtime = await HubloomRuntime.from_config_file(cfg_path)
        try:
            yield
        finally:
            if _runtime is not None and injected is None:
                await _runtime.aclose()
            _runtime = None

    app = FastAPI(
        title="Hubloom",
        description=(
            "Hubloom Agent HTTP API（Typed ReAct）。"
            "无 A2UI / AG-UI；interactive 用 /v1/chat/resume。"
        ),
        version="0.3.0",
        lifespan=lifespan,
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/v1/mcp/status", response_model=McpStatusResponse)
    async def mcp_status() -> McpStatusResponse:
        if _runtime is None:
            raise HTTPException(status_code=503, detail="运行时尚未初始化")
        setup = _runtime.mcp_setup
        if setup is None:
            return McpStatusResponse(
                status="disabled",
                mcp_ready=False,
                detail="mcp.enable=false 或未加载",
            )
        catalog = setup.catalog
        groups = getattr(catalog, "groups", None) or []
        tools = list(_runtime._mcp_tools)
        return McpStatusResponse(
            status="ready",
            mcp_ready=True,
            swagger_url=(_runtime.cfg.mcp_swagger_url or ""),
            base_url=(_runtime.cfg.mcp_base_url or ""),
            group_count=len(groups) if hasattr(groups, "__len__") else 0,
            tool_count=len(tools),
            detail="",
        )

    @app.post("/v1/chat")
    async def chat(
        body: ChatRequest,
        authorization: str | None = Header(default=None),
        x_session_id: str | None = Header(default=None, alias="X-Session-Id"),
        x_mcp_token: str | None = Header(default=None, alias="X-MCP-Token"),
    ):
        if _runtime is None:
            raise HTTPException(status_code=503, detail="运行时尚未初始化")

        session_id = _resolve_session_id(body.session_id, x_session_id)
        if not session_id:
            raise HTTPException(status_code=400, detail="请填写 session_id")

        # Token 可选：有则注入 request context；无则仍可对话（只读/无鉴权 MCP 场景）
        bearer = _bearer_from_headers(authorization, x_mcp_token)
        if not bearer:
            bearer = (_runtime.cfg.mcp_token or "").strip() or None

        message = body.message.strip()
        if body.stream:
            return StreamingResponse(
                _stream_chat(
                    message,
                    session_id=session_id,
                    bearer_token=bearer,
                    wait_profile=body.wait_profile,
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
            session_id=session_id,
            bearer_token=bearer,
            wait_profile=body.wait_profile,
        )
        return JSONResponse(content=_result_to_sync(session_id, result).model_dump())

    @app.post("/v1/chat/resume")
    async def chat_resume(
        body: ResumeRequest,
        authorization: str | None = Header(default=None),
        x_session_id: str | None = Header(default=None, alias="X-Session-Id"),
        x_mcp_token: str | None = Header(default=None, alias="X-MCP-Token"),
    ):
        if _runtime is None:
            raise HTTPException(status_code=503, detail="运行时尚未初始化")

        session_id = _resolve_session_id(body.session_id, x_session_id)
        if not session_id:
            raise HTTPException(status_code=400, detail="请填写 session_id")

        bearer = _bearer_from_headers(authorization, x_mcp_token)
        if not bearer:
            bearer = (_runtime.cfg.mcp_token or "").strip() or None

        if body.stream:
            return StreamingResponse(
                _stream_resume(
                    body.user_reply.strip(),
                    session_id=session_id,
                    bearer_token=bearer,
                    run_id=body.run_id,
                    await_token=body.await_token,
                ),
                media_type="text/event-stream",
                headers={
                    "Cache-Control": "no-cache",
                    "Connection": "keep-alive",
                    "X-Accel-Buffering": "no",
                },
            )

        result = await _run_resume_once(
            body.user_reply.strip(),
            session_id=session_id,
            bearer_token=bearer,
            run_id=body.run_id,
            await_token=body.await_token,
        )
        return JSONResponse(content=_result_to_sync(session_id, result).model_dump())

    @app.get("/v1/chat/history", response_model=ChatHistoryResponse)
    async def chat_history(
        session_id: str | None = Query(default=None),
        x_session_id: str | None = Header(default=None, alias="X-Session-Id"),
    ) -> ChatHistoryResponse:
        if _runtime is None:
            raise HTTPException(status_code=503, detail="运行时尚未初始化")
        resolved = _resolve_session_id(session_id, x_session_id)
        if not resolved:
            raise HTTPException(status_code=400, detail="请填写 session_id")

        store = ConversationSQLitesStore(_runtime.memory_db_path)
        try:
            rows = await asyncio.to_thread(store.get_chat_history, resolved)
        finally:
            store.close()

        messages = _history_messages(rows)
        return ChatHistoryResponse(
            session_id=resolved,
            messages=messages,
            total=len(messages),
        )

    return app


async def _stream_chat(
    message: str,
    *,
    session_id: str,
    bearer_token: str | None,
    wait_profile: str | None,
) -> AsyncIterator[str]:
    assert _runtime is not None
    run_id = uuid.uuid4().hex[:12]
    async with _run_lock:
        yield format_sse(
            "run_started",
            {"session_id": session_id, "run_id": run_id, "mode": "chat"},
        )
        try:
            async for item in _runtime.run_stream(
                Message(role=Role.USER, content=message),
                session_id=session_id,
                bearer_token=bearer_token,
                wait_profile=wait_profile,
                trigger_source="user",
            ):
                line = event_to_sse(item, session_id=session_id, run_id=run_id)
                if line:
                    yield line
        except Exception as exc:
            yield format_sse(
                "error",
                {
                    "session_id": session_id,
                    "run_id": run_id,
                    "error": str(exc),
                    "recoverable": False,
                },
            )
        yield format_sse(
            "run_finished",
            {"session_id": session_id, "run_id": run_id},
        )


async def _stream_resume(
    user_reply: str,
    *,
    session_id: str,
    bearer_token: str | None,
    run_id: str | None,
    await_token: str | None,
) -> AsyncIterator[str]:
    assert _runtime is not None
    stream_run_id = (run_id or "").strip() or uuid.uuid4().hex[:12]
    async with _run_lock:
        yield format_sse(
            "run_started",
            {
                "session_id": session_id,
                "run_id": stream_run_id,
                "mode": "resume",
            },
        )
        try:
            async for item in _runtime.resume_stream(
                session_id=session_id,
                user_reply=user_reply,
                bearer_token=bearer_token,
                run_id=run_id,
                await_token=await_token,
                trigger_source="user",
            ):
                line = event_to_sse(
                    item, session_id=session_id, run_id=stream_run_id
                )
                if line:
                    yield line
        except Exception as exc:
            yield format_sse(
                "error",
                {
                    "session_id": session_id,
                    "run_id": stream_run_id,
                    "error": str(exc),
                    "recoverable": False,
                },
            )
        yield format_sse(
            "run_finished",
            {"session_id": session_id, "run_id": stream_run_id},
        )


async def _run_chat_once(
    message: str,
    *,
    session_id: str,
    bearer_token: str | None,
    wait_profile: str | None,
) -> RunResult:
    assert _runtime is not None
    async with _run_lock:
        final: RunResult | None = None
        async for item in _runtime.run_stream(
            Message(role=Role.USER, content=message),
            session_id=session_id,
            bearer_token=bearer_token,
            wait_profile=wait_profile,
            trigger_source="user",
        ):
            if isinstance(item, RunResult):
                final = item
        if final is None:
            return RunResult(ok=False, status="failed", error="未收到编排结果")
        return final


async def _run_resume_once(
    user_reply: str,
    *,
    session_id: str,
    bearer_token: str | None,
    run_id: str | None,
    await_token: str | None,
) -> RunResult:
    assert _runtime is not None
    async with _run_lock:
        final: RunResult | None = None
        async for item in _runtime.resume_stream(
            session_id=session_id,
            user_reply=user_reply,
            bearer_token=bearer_token,
            run_id=run_id,
            await_token=await_token,
            trigger_source="user",
        ):
            if isinstance(item, RunResult):
                final = item
        if final is None:
            return RunResult(ok=False, status="failed", error="未收到编排结果")
        return final
