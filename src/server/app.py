"""Hubloom FastAPI 应用：Typed ReAct 产品 API + Events + 企微。"""

from __future__ import annotations

import asyncio
import json
import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from fastapi import FastAPI, Header, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, Response, StreamingResponse

from agent.run import RunResult
from core.models import Message, Role
from events.dispatcher import EventDispatcher
from events.models import normalize_event
from im.wecom.adapter import WeComChatAdapter
from im.wecom.crypto import WeComCryptoError
from observability import setup_log
from runtime import HubloomRuntime
from server.assembly import (
    build_event_dispatcher,
    build_wecom_adapter,
    check_event_secret,
)
from server.schemas import (
    ChatHistoryResponse,
    ChatRequest,
    ChatSyncResponse,
    EventIngestResponse,
    HistoryMessage,
    HistoryToolBlock,
    McpStatusResponse,
    ResumeRequest,
)
from server.sse import event_to_sse, format_sse

_runtime: HubloomRuntime | None = None
_dispatcher: EventDispatcher | None = None
_wecom: WeComChatAdapter | None = None


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


def _row_has_tool_calls(row: dict[str, Any]) -> bool:
    raw = row.get("tool_calls_json")
    if not isinstance(raw, str) or not raw.strip():
        return False
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return bool(raw.strip())
    return isinstance(data, list) and len(data) > 0


def _parse_tool_calls(row: dict[str, Any]) -> list[dict[str, Any]]:
    raw = row.get("tool_calls_json")
    if not isinstance(raw, str) or not raw.strip():
        return []
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return []
    if not isinstance(data, list):
        return []
    return [x for x in data if isinstance(x, dict)]


def _extract_history_meta(
    row: dict[str, Any],
) -> tuple[str | None, str | None, bool | None]:
    """返回 (source, reasoning_content, is_error)。"""
    meta_raw = row.get("metadata_json") or row.get("metadata")
    source = row.get("source")
    reasoning: str | None = None
    is_error: bool | None = None
    if isinstance(meta_raw, str) and meta_raw.strip():
        try:
            meta = json.loads(meta_raw)
            if isinstance(meta, dict):
                if meta.get("source"):
                    source = meta.get("source")
                raw_thought = meta.get("reasoning_content")
                if raw_thought is not None:
                    text = str(raw_thought).strip()
                    reasoning = text or None
                if "is_error" in meta:
                    is_error = bool(meta.get("is_error"))
        except json.JSONDecodeError:
            pass
    return (str(source) if source else None, reasoning, is_error)


def _tool_call_blocks(row: dict[str, Any]) -> list[HistoryToolBlock]:
    blocks: list[HistoryToolBlock] = []
    for tc in _parse_tool_calls(row):
        name = str(tc.get("name") or "tool").strip() or "tool"
        args = tc.get("arguments") if isinstance(tc.get("arguments"), dict) else {}
        blocks.append(
            HistoryToolBlock(
                title=f"调用 · {name}",
                body=json.dumps(args, ensure_ascii=False, indent=2),
            )
        )
    return blocks


def _history_messages(
    rows: list[dict[str, Any]],
    *,
    include_thought: bool = False,
) -> list[HistoryMessage]:
    """面向聊天 UI：把中间轮折叠进最终助手气泡（thought + tools），对齐实时 SSE。"""
    out: list[HistoryMessage] = []
    pending_thoughts: list[str] = []
    pending_tools: list[HistoryToolBlock] = []

    for row in rows:
        role = str(row.get("role") or "").strip()
        if role not in ("user", "assistant", "tool"):
            continue

        content = str(row.get("content") or "")
        source, reasoning, is_error = _extract_history_meta(row)

        if role == "user":
            pending_thoughts = []
            pending_tools = []
            out.append(
                HistoryMessage(
                    role="user",
                    content=content,
                    created_at=row.get("created_at"),
                    source=source,
                    thought=None,
                    tools=None,
                )
            )
            continue

        if role == "tool":
            name = str(row.get("name") or "").strip() or "tool"
            label = "失败" if is_error else "返回"
            pending_tools.append(
                HistoryToolBlock(
                    title=f"{label} · {name}",
                    body=content,
                )
            )
            continue

        # assistant
        if _row_has_tool_calls(row):
            pending_tools.extend(_tool_call_blocks(row))
            if include_thought:
                if reasoning:
                    pending_thoughts.append(reasoning)
                text = content.strip()
                if text:
                    pending_thoughts.append(text)
            continue

        thought: str | None = None
        if include_thought:
            parts = list(pending_thoughts)
            if reasoning:
                parts.append(reasoning)
            thought = "\n\n".join(parts) if parts else None

        tools = list(pending_tools) if pending_tools else None
        pending_thoughts = []
        pending_tools = []

        out.append(
            HistoryMessage(
                role="assistant",
                content=content,
                created_at=row.get("created_at"),
                source=source,
                thought=thought,
                tools=tools,
            )
        )

    return out


def create_app(
    *,
    config_path: str | Path | None = None,
    runtime: HubloomRuntime | None = None,
    event_dispatcher: EventDispatcher | None = None,
    wecom_adapter: WeComChatAdapter | None = None,
) -> FastAPI:
    """构造 Hubloom Serve 应用。

    - 生产：传 ``config_path``，lifespan 内装配 Runtime / Events / 企微
    - 单测：注入 ``runtime``；可再注入 ``event_dispatcher`` / ``wecom_adapter``
    """
    cfg_path = Path(config_path).resolve() if config_path else None
    injected = runtime
    injected_dispatcher = event_dispatcher
    injected_wecom = wecom_adapter

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        global _runtime, _dispatcher, _wecom
        del app
        setup_log()
        if injected is not None:
            _runtime = injected
        else:
            if cfg_path is None or not cfg_path.is_file():
                raise FileNotFoundError(f"配置文件不存在: {cfg_path}")
            _runtime = await HubloomRuntime.from_config_file(cfg_path)

        if injected_dispatcher is not None:
            _dispatcher = injected_dispatcher
        else:
            try:
                _dispatcher = build_event_dispatcher(_runtime)
            except Exception as exc:
                _dispatcher = None
                raise RuntimeError(f"装配 Events 失败: {exc}") from exc

        if injected_wecom is not None:
            _wecom = injected_wecom
        else:
            try:
                _wecom = build_wecom_adapter(_runtime)
            except Exception as exc:
                _wecom = None
                raise RuntimeError(f"装配企微失败: {exc}") from exc

        try:
            yield
        finally:
            if _wecom is not None and _wecom.session_worker is not None:
                for task in list(_wecom.session_worker._tasks.values()):
                    task.cancel()
            if _runtime is not None and injected is None:
                await _runtime.aclose()
            _runtime = None
            _dispatcher = None
            _wecom = None

    app = FastAPI(
        title="Hubloom",
        description=(
            "Hubloom Agent HTTP API（Typed ReAct）。"
            "含 /v1/chat、/v1/events、企微回调；无 A2UI / AG-UI。"
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
    async def health():
        return {
            "status": "ok",
            "events_enabled": bool(
                _runtime is not None and _runtime.cfg.events_enable and _dispatcher
            ),
            "wecom_enabled": bool(
                _runtime is not None and _runtime.cfg.wecom_enable and _wecom
            ),
        }

    @app.get("/v1/mcp/status", response_model=McpStatusResponse)
    async def mcp_status() -> McpStatusResponse:
        if _runtime is None:
            raise HTTPException(status_code=503, detail="运行时尚未初始化")
        if _runtime.mcp_setup is None:
            return McpStatusResponse(
                status="disabled",
                mcp_ready=False,
                detail="mcp.enable=false 或未装配",
            )
        tools = _runtime._mcp_tools
        groups = getattr(_runtime.mcp_setup.catalog, "groups", []) or []
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

        bearer = _bearer_from_headers(authorization, x_mcp_token)
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
        include_thought: bool = Query(
            default=False,
            description="为 true 时在消息中填回 thought（来自落库的 reasoning_content）",
        ),
    ) -> ChatHistoryResponse:
        if _runtime is None:
            raise HTTPException(status_code=503, detail="运行时尚未初始化")
        resolved = _resolve_session_id(session_id, x_session_id)
        if not resolved:
            raise HTTPException(status_code=400, detail="请填写 session_id")

        store = _runtime.conversation_store
        rows = await asyncio.to_thread(store.get_chat_history, resolved)
        messages = _history_messages(rows, include_thought=include_thought)
        return ChatHistoryResponse(
            session_id=resolved,
            messages=messages,
            total=len(messages),
        )

    # ----- Events -----

    @app.get("/v1/events/types")
    async def list_event_types(
        x_event_secret: str | None = Header(default=None, alias="X-Event-Secret"),
    ):
        if _runtime is None:
            raise HTTPException(status_code=503, detail="运行时尚未初始化")
        if not _runtime.cfg.events_enable or _dispatcher is None:
            raise HTTPException(status_code=503, detail="events.enable=false")
        check_event_secret(_runtime.cfg, x_event_secret)
        types = _dispatcher.catalog.list_types()
        return {
            "skill_id": "events",
            "events_dir": _dispatcher.catalog.events_dir,
            "types": types,
            "total": len(types),
        }

    @app.post("/v1/events", response_model=EventIngestResponse)
    async def ingest_event(
        request: Request,
        x_event_secret: str | None = Header(default=None, alias="X-Event-Secret"),
    ):
        if _runtime is None:
            raise HTTPException(status_code=503, detail="运行时尚未初始化")
        if not _runtime.cfg.events_enable or _dispatcher is None:
            raise HTTPException(status_code=503, detail="events.enable=false")
        check_event_secret(_runtime.cfg, x_event_secret)

        try:
            body = await request.json()
        except Exception as exc:
            raise HTTPException(status_code=400, detail="请求体须为 JSON") from exc
        try:
            event = normalize_event(body if isinstance(body, dict) else {})
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

        try:
            async with _runtime.session_lock.hold(event.session_id):
                result = await _dispatcher.dispatch(event)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except KeyError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

        return EventIngestResponse(**result.to_dict())

    # ----- 企微回调 -----

    @app.get("/v1/im/wecom/callback")
    async def wecom_verify(
        msg_signature: str = Query(...),
        timestamp: str = Query(...),
        nonce: str = Query(...),
        echostr: str = Query(...),
    ):
        if _runtime is None:
            raise HTTPException(status_code=503, detail="运行时尚未初始化")
        if not _runtime.cfg.wecom_enable or _wecom is None:
            raise HTTPException(status_code=503, detail="im.wecom.enable=false")
        try:
            plain = _wecom.verify_url(
                msg_signature=msg_signature,
                timestamp=timestamp,
                nonce=nonce,
                echostr=echostr,
            )
        except WeComCryptoError as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from exc
        return Response(content=plain, media_type="text/plain")

    @app.post("/v1/im/wecom/callback")
    async def wecom_on_message(
        request: Request,
        msg_signature: str = Query(...),
        timestamp: str = Query(...),
        nonce: str = Query(...),
    ):
        if _runtime is None:
            raise HTTPException(status_code=503, detail="运行时尚未初始化")
        if not _runtime.cfg.wecom_enable or _wecom is None:
            raise HTTPException(status_code=503, detail="im.wecom.enable=false")

        post_data = await request.body()
        try:
            _plain, msg = _wecom.handle_callback_sync_ack(
                msg_signature=msg_signature,
                timestamp=timestamp,
                nonce=nonce,
                post_data=post_data,
            )
        except WeComCryptoError as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from exc

        if msg is not None:
            _wecom.schedule_handle_message(msg)
        # 必须尽快空 200，Agent 异步处理
        return Response(content=b"", media_type="text/plain")

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
    async with _runtime.session_lock.hold(session_id):
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
        except TimeoutError as exc:
            yield format_sse(
                "error",
                {
                    "session_id": session_id,
                    "run_id": run_id,
                    "error": str(exc),
                    "recoverable": True,
                },
            )
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
    async with _runtime.session_lock.hold(session_id):
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
        except TimeoutError as exc:
            yield format_sse(
                "error",
                {
                    "session_id": session_id,
                    "run_id": stream_run_id,
                    "error": str(exc),
                    "recoverable": True,
                },
            )
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
    async with _runtime.session_lock.hold(session_id):
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
    async with _runtime.session_lock.hold(session_id):
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
