"""Hubloom 对话示例站 HTTP API（FastAPI）。

接口：
- ``POST /v1/chat`` — SSE / 非流式对话
- ``GET  /v1/chat/history`` — 会话历史
- ``POST /v1/events`` — 业务事件入站（需配置 events.enable）
- ``GET  /v1/events/types`` — 支持的事件类型（扫 skills/events）
- ``GET  /v1/mcp/status`` — MCP 就绪状态
- ``GET  /health``

启动（仓库根）::

    PYTHONPATH=src:. uv run python main.py
"""

from __future__ import annotations

import asyncio
import os
import secrets
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from fastapi import FastAPI, Header, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, StreamingResponse

from agent.events import A2uiMessagesEvent, ErrorEvent
from agent.loop.respond import PresentMode
from agent.run import RunResult
from agent.sse import (
    AguiStreamEncoder,
    a2ui_client_tool_call_sse,
    a2ui_client_tool_result_sse,
    format_sse,
    run_started_payload,
    turn_complete_payload,
)
from agent.turn_state import (
    answer_parts_need_human,
    default_turn_store,
    new_tool_call_id,
)
from context import clear_request_context
from core.models import Message, Role
from events import EventDispatcher, normalize_event
from events.catalog import EventCatalog, resolve_events_skill_dir
from memory.store.conversation_sqlite_store import ConversationSQLitesStore
from observability import setup_log
from runtime import HubloomRuntime

from examples.chat.action_format import action_to_tool_messages, format_action_trigger
from examples.chat.client_headers import ClientHeaderContext, parse_client_headers
from examples.chat.history import ChatHistoryResponse, messages_for_display
from examples.chat.schemas import (
    ChatAction,
    ChatRequest,
    ChatResponse,
    EventIngestResponse,
    McpStatusResponse,
)

_runtime: HubloomRuntime | None = None
_dispatcher: EventDispatcher | None = None
_run_lock = asyncio.Lock()
_turn_store = default_turn_store


def _sse_interaction_superseded(pending, *, session_id: str, new_run_id: str) -> str:
    """通知前端：旧表单因用户改走对话而被覆盖。"""
    name, payload = (
        "CUSTOM",
        {
            "type": "CUSTOM",
            "name": "hubloom.interaction_superseded",
            "value": {
                "reason": "user_message",
                "old_run_id": pending.run_id,
                "new_run_id": new_run_id,
                "kind": pending.kind,
            },
            "session_id": session_id,
        },
    )
    return format_sse(name, payload)


def _sse_interaction_waiting(
    *,
    session_id: str,
    run_id: str,
    tool_call_id: str,
) -> str:
    name, payload = (
        "CUSTOM",
        {
            "type": "CUSTOM",
            "name": "hubloom.interaction_waiting",
            "value": {
                "run_id": run_id,
                "kind": "a2ui",
                "tool_call_id": tool_call_id,
            },
            "session_id": session_id,
        },
    )
    return format_sse(name, payload)


def _mark_waiting_a2ui(session_id: str, run_id: str) -> str:
    """进入人机等待，分配 toolCallId；返回该 id。"""
    tcid = new_tool_call_id()
    _turn_store.mark_waiting(
        session_id,
        run_id,
        kind="a2ui",
        meta={"tool_call_id": tcid},
    )
    return tcid


def _resolve_action_tool_call_id(
    pending_meta: dict,
    action: ChatAction,
) -> str:
    expected = str((pending_meta or {}).get("tool_call_id") or "").strip()
    got = (action.tool_call_id or "").strip()
    if got and expected and got != expected:
        raise ValueError(
            f"tool_call_id 与当前等待中的交互不一致："
            f"expect={expected!r} got={got!r}"
        )
    return got or expected or new_tool_call_id()

_ROOT = Path(__file__).resolve().parents[2]
_DEFAULT_CONFIG = _ROOT / "config" / "env.yaml"


def _config_path() -> Path:
    raw = (os.getenv("HUBLOOM_CONFIG") or "").strip()
    return Path(raw) if raw else _DEFAULT_CONFIG


def _resolve_session_id(
    body_session: str | None,
    header_session: str | None,
) -> str:
    for value in (body_session, header_session):
        if value and value.strip():
            return value.strip()
    return ""


def _normalize_present_mode(raw: str | None, default: PresentMode) -> PresentMode:
    text = (raw or "").strip().lower()
    if not text:
        return default
    if text in ("markdown", "a2ui", "auto"):
        return text  # type: ignore[return-value]
    raise HTTPException(
        status_code=400,
        detail=f"present_mode 无效: {raw!r}，可选 markdown / a2ui / auto",
    )


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
    global _runtime, _dispatcher
    # 写入 logs/debug.log（默认不刷控制台，避免与 uvicorn access 叠两份）
    setup_log()
    cfg_path = _config_path()
    if not cfg_path.is_file():
        raise RuntimeError(f"配置文件不存在: {cfg_path}")
    present = (os.getenv("PRESENT_MODE") or "a2ui").strip().lower()
    if present not in ("markdown", "a2ui", "auto"):
        present = "a2ui"
    _runtime = await HubloomRuntime.from_config_file(
        cfg_path,
        default_present_mode=present,  # type: ignore[arg-type]
    )
    events_dir = resolve_events_skill_dir(
        skills_dir=_runtime.cfg.skills_dir,
        source_path=_runtime.cfg.source_path,
    )
    catalog = EventCatalog.load(
        events_dir=events_dir,
        config_catalog=_runtime.cfg.events_catalog,
    )
    _dispatcher = EventDispatcher(
        catalog=catalog,
        result_callback_url=_runtime.cfg.events_result_callback_url,
        default_bearer_token=_runtime.cfg.events_default_bearer_token,
        present_mode="markdown",
    )
    _dispatcher.bind_runtime(_runtime)
    try:
        yield
    finally:
        if _runtime is not None:
            await _runtime.aclose()
        _runtime = None
        _dispatcher = None


app = FastAPI(
    title="Hubloom Chat",
    description="示例站：HubloomRuntime + SSE 对话 / 历史 / 事件入站",
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


def _check_event_secret(header_secret: str | None) -> None:
    assert _runtime is not None
    expected = (_runtime.cfg.events_shared_secret or "").strip()
    if not expected:
        return
    got = (header_secret or "").strip()
    if not got or not secrets.compare_digest(got, expected):
        raise HTTPException(status_code=401, detail="无效的 X-Event-Secret")


@app.get("/v1/events/types")
async def list_event_types(
    x_event_secret: str | None = Header(default=None, alias="X-Event-Secret"),
) -> dict[str, Any]:
    """列出当前支持的事件类型（来自 ``skills/events/*.md`` 扫描）。"""
    if _runtime is None or _dispatcher is None:
        raise HTTPException(status_code=503, detail="运行时尚未初始化")
    if not _runtime.cfg.events_enable:
        raise HTTPException(status_code=503, detail="事件入口未启用（events.enable=false）")
    _check_event_secret(x_event_secret)
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
) -> EventIngestResponse:
    """业务推送事件：注入分册规程后主动跑一轮 Agent，写入指定 session 历史。"""
    if _runtime is None or _dispatcher is None:
        raise HTTPException(status_code=503, detail="运行时尚未初始化")
    if not _runtime.cfg.events_enable:
        raise HTTPException(status_code=503, detail="事件入口未启用（events.enable=false）")

    _check_event_secret(x_event_secret)

    try:
        body: Any = await request.json()
    except Exception as exc:
        raise HTTPException(status_code=400, detail="请求体须为 JSON object") from exc

    try:
        event = normalize_event(body if isinstance(body, dict) else {})
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    async with _run_lock:
        try:
            result = await _dispatcher.dispatch(event)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    return EventIngestResponse(**result.to_dict())


@app.get("/v1/mcp/status", response_model=McpStatusResponse)
async def mcp_status() -> McpStatusResponse:
    if _runtime is None:
        raise HTTPException(status_code=503, detail="运行时尚未初始化")

    cfg = _runtime.cfg
    swagger_url = (cfg.mcp_swagger_url or "").strip()
    base_url = (cfg.mcp_base_url or "").strip()
    mcp_ready = bool(_runtime.mcp_setup is not None and _runtime._mcp_tools)
    tool_count = len(_runtime._mcp_tools)
    group_count = 0
    detail = ""

    if mcp_ready and _runtime.mcp_setup is not None:
        catalog = _runtime.mcp_setup.catalog
        if catalog is not None and getattr(catalog, "groups", None):
            group_count = len(catalog.groups)
        detail = f"已连接 · {tool_count} 工具"
    elif not cfg.enable_mcp:
        detail = "mcp.enable=false"
    else:
        detail = "服务端 MCP 未就绪，请检查 config/env.yaml 中的 mcp.swagger_url"

    return McpStatusResponse(
        status="ok" if mcp_ready or not cfg.enable_mcp else "error",
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
    if _runtime is None:
        raise HTTPException(status_code=503, detail="运行时尚未初始化")

    session_id = _resolve_session_id(body.session_id, x_session_id)
    if not session_id:
        raise HTTPException(status_code=400, detail="请填写 session_id（用户 ID）")

    client_ctx = parse_client_headers(
        authorization=authorization,
        x_mcp_token=x_mcp_token,
    )
    if not client_ctx["bearer_token"] and not (_runtime.cfg.mcp_token or "").strip():
        raise HTTPException(
            status_code=400,
            detail="请在前端填写业务 Token（X-MCP-Token / Authorization）",
        )

    present_mode = _normalize_present_mode(
        body.present_mode,
        _runtime.default_present_mode,
    )

    if body.action is not None:
        assert body.run_id is not None
        trigger_text = ""
        trigger_kind = "action"
        action = body.action
        action_run_id = body.run_id
    else:
        trigger_text = (body.message or "").strip()
        if not trigger_text:
            raise HTTPException(status_code=400, detail="message 不能为空")
        trigger_kind = "message"
        action = None
        action_run_id = None

    if body.stream:
        return StreamingResponse(
            _stream_chat(
                trigger_text,
                session_id=session_id,
                client_ctx=client_ctx,
                present_mode=present_mode,
                trigger_kind=trigger_kind,
                action=action,
                action_run_id=action_run_id,
            ),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                "X-Accel-Buffering": "no",
            },
        )

    result = await _run_chat_once(
        trigger_text,
        session_id=session_id,
        client_ctx=client_ctx,
        present_mode=present_mode,
        trigger_kind=trigger_kind,
        action=action,
        action_run_id=action_run_id,
    )
    return JSONResponse(content=result.model_dump())


@app.get("/v1/chat/history", response_model=ChatHistoryResponse)
async def chat_history(
    session_id: str | None = Query(default=None, description="会话 ID"),
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
    client_ctx: ClientHeaderContext,
    present_mode: PresentMode,
    trigger_kind: str = "message",
    action: ChatAction | None = None,
    action_run_id: str | None = None,
) -> AsyncIterator[str]:
    """流式跑一轮。

    - ``message``：新用户话；若正 waiting 则 supersede。
    - ``action``：译为 tool 消息对后进 Runtime。
    """
    assert _runtime is not None
    async with _run_lock:
        try:
            trigger_source = "user"
            if trigger_kind == "action":
                if action is None or not action_run_id:
                    yield format_sse(
                        "RUN_ERROR",
                        {
                            "type": "RUN_ERROR",
                            "message": "action 缺少 run_id",
                            "session_id": session_id,
                        },
                    )
                    return
                try:
                    resolved = _turn_store.resolve_action(
                        session_id,
                        action_run_id,
                        resolution=action.type,
                    )
                    tcid = _resolve_action_tool_call_id(resolved.meta, action)
                    trigger: Message | list[Message] = action_to_tool_messages(
                        action,
                        tool_call_id=tcid,
                        source_run_id=action_run_id,
                    )
                except ValueError as exc:
                    yield format_sse(
                        "RUN_ERROR",
                        {
                            "type": "RUN_ERROR",
                            "message": str(exc),
                            "session_id": session_id,
                        },
                    )
                    return
                # 先关闭上一轮客户端工具，再开续跑 run
                yield a2ui_client_tool_result_sse(
                    tool_call_id=tcid,
                    content=format_action_trigger(action),
                    session_id=session_id,
                )
                run_id = _turn_store.begin_run(session_id)
                trigger_source = "action"
            else:
                superseded = _turn_store.supersede_if_waiting(session_id)
                run_id = _turn_store.begin_run(session_id)
                if superseded is not None:
                    yield _sse_interaction_superseded(
                        superseded, session_id=session_id, new_run_id=run_id
                    )
                trigger = Message(role=Role.USER, content=message)

            started_name, started_payload = run_started_payload(
                session_id=session_id, run_id=run_id
            )
            started_payload["session_id"] = session_id
            if trigger_kind == "action" and action_run_id:
                started_payload["rawEvent"] = {
                    "trigger": "action",
                    "source_run_id": action_run_id,
                }
            yield format_sse(started_name, started_payload)

            encoder = AguiStreamEncoder(session_id=session_id, run_id=run_id)
            final: RunResult | None = None
            saw_a2ui = False
            async for item in _runtime.run_stream(
                trigger,
                session_id=session_id,
                present_mode=present_mode,
                bearer_token=client_ctx["bearer_token"],
                trigger_source=trigger_source,
            ):
                if isinstance(item, RunResult):
                    final = item
                    continue
                if isinstance(item, A2uiMessagesEvent):
                    saw_a2ui = True
                chunk = encoder.feed(item)
                if chunk:
                    yield chunk
                if isinstance(item, ErrorEvent) and not item.recoverable:
                    closed = encoder.flush()
                    if closed:
                        yield closed
                    return

            # 结束未闭合的文本/思考，再发客户端 TOOL_CALL / RUN_FINISHED
            closed = encoder.flush()
            if closed:
                yield closed

            if final is not None:
                if saw_a2ui or answer_parts_need_human(final.answer_parts):
                    tcid = _mark_waiting_a2ui(session_id, run_id)
                    yield a2ui_client_tool_call_sse(
                        tool_call_id=tcid,
                        run_id=run_id,
                        session_id=session_id,
                    )
                    yield _sse_interaction_waiting(
                        session_id=session_id,
                        run_id=run_id,
                        tool_call_id=tcid,
                    )
                name, payload = turn_complete_payload(
                    route=final.present_mode,
                    final_message=(final.content or "").strip(),
                    session_id=session_id,
                    reason="" if final.ok else (final.error or ""),
                    answer_parts=list(final.answer_parts or []) or None,
                )
                # 固定本轮 runId，便于前端绑定面板
                payload["runId"] = run_id
                payload["threadId"] = session_id
                if isinstance(payload.get("result"), dict):
                    payload["result"]["run_id"] = run_id
                yield format_sse(name, payload)
        except Exception as exc:
            yield format_sse(
                "RUN_ERROR",
                {
                    "type": "RUN_ERROR",
                    "message": str(exc),
                    "session_id": session_id,
                },
            )
        finally:
            clear_request_context()


async def _run_chat_once(
    message: str,
    *,
    session_id: str,
    client_ctx: ClientHeaderContext,
    present_mode: PresentMode,
    trigger_kind: str = "message",
    action: ChatAction | None = None,
    action_run_id: str | None = None,
) -> ChatResponse:
    assert _runtime is not None
    async with _run_lock:
        try:
            trigger_source = "user"
            if trigger_kind == "action":
                if action is None or not action_run_id:
                    raise HTTPException(status_code=400, detail="action 缺少 run_id")
                try:
                    resolved = _turn_store.resolve_action(
                        session_id,
                        action_run_id,
                        resolution=action.type,
                    )
                    tcid = _resolve_action_tool_call_id(resolved.meta, action)
                    trigger: Message | list[Message] = action_to_tool_messages(
                        action,
                        tool_call_id=tcid,
                        source_run_id=action_run_id,
                    )
                except ValueError as exc:
                    raise HTTPException(status_code=400, detail=str(exc)) from exc
                trigger_source = "action"
            else:
                _turn_store.supersede_if_waiting(session_id)
                trigger = Message(role=Role.USER, content=message)
            run_id = _turn_store.begin_run(session_id)
            final: RunResult | None = None
            saw_a2ui = False
            async for item in _runtime.run_stream(
                trigger,
                session_id=session_id,
                present_mode=present_mode,
                bearer_token=client_ctx["bearer_token"],
                trigger_source=trigger_source,
            ):
                if isinstance(item, RunResult):
                    final = item
                elif isinstance(item, A2uiMessagesEvent):
                    saw_a2ui = True
                elif isinstance(item, ErrorEvent) and not item.recoverable:
                    raise HTTPException(status_code=500, detail=item.error)
            if final is not None and (
                saw_a2ui or answer_parts_need_human(final.answer_parts)
            ):
                _mark_waiting_a2ui(session_id, run_id)
        finally:
            clear_request_context()

    if final is None:
        raise HTTPException(status_code=500, detail="未收到编排结果")
    if not final.ok:
        raise HTTPException(status_code=500, detail=final.error or "运行失败")

    return ChatResponse(
        route=final.present_mode,
        final_message=(final.content or "").strip(),
        session_id=session_id,
        reason="",
        answer_parts=list(final.answer_parts or []) or None,
        run_id=run_id,
    )


def main() -> None:
    import uvicorn

    host = os.getenv("CORTEX_API_HOST", "0.0.0.0")
    port = int(os.getenv("CORTEX_API_PORT", "8010"))
    reload = os.getenv("CORTEX_API_RELOAD", "").lower() in ("1", "true", "yes")
    # reload 时需字符串导入，且进程环境带 PYTHONPATH=src:.
    if reload:
        uvicorn.run(
            "examples.chat.app:app",
            host=host,
            port=port,
            reload=True,
        )
    else:
        uvicorn.run(app, host=host, port=port)


if __name__ == "__main__":
    main()
