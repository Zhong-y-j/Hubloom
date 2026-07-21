"""Hubloom 对话示例站 HTTP API（FastAPI）。

接口：
- ``POST /v1/chat`` — SSE / 非流式对话
- ``GET  /v1/chat/history`` — 会话历史
- ``GET  /v1/mcp/status`` — MCP 就绪状态
- ``GET  /health``

启动（仓库根）::

    PYTHONPATH=src:. uv run python main.py
"""

from __future__ import annotations

import asyncio
import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Header, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, StreamingResponse

from agent.events import ErrorEvent
from agent.loop.respond import PresentMode
from agent.run import RunResult
from agent.sse import event_to_sse, format_sse, turn_complete_payload
from context import clear_request_context
from core.models import Message, Role
from memory.store.conversation_sqlite_store import ConversationSQLitesStore
from observability import setup_log
from runtime import HubloomRuntime

from examples.chat.client_headers import ClientHeaderContext, parse_client_headers
from examples.chat.history import ChatHistoryResponse, messages_for_display
from examples.chat.schemas import (
    ChatRequest,
    ChatResponse,
    McpStatusResponse,
)

_runtime: HubloomRuntime | None = None
_run_lock = asyncio.Lock()

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
    if text in ("markdown", "a2ui"):
        return text  # type: ignore[return-value]
    raise HTTPException(
        status_code=400,
        detail=f"present_mode 无效: {raw!r}，可选 markdown / a2ui",
    )


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
    global _runtime
    # 写入 logs/debug.log（默认不刷控制台，避免与 uvicorn access 叠两份）
    setup_log()
    cfg_path = _config_path()
    if not cfg_path.is_file():
        raise RuntimeError(f"配置文件不存在: {cfg_path}")
    present = (os.getenv("PRESENT_MODE") or "a2ui").strip().lower()
    if present not in ("markdown", "a2ui"):
        present = "a2ui"
    _runtime = await HubloomRuntime.from_config_file(
        cfg_path,
        default_present_mode=present,  # type: ignore[arg-type]
    )
    try:
        yield
    finally:
        if _runtime is not None:
            await _runtime.aclose()
        _runtime = None


app = FastAPI(
    title="Hubloom Chat",
    description="示例站：HubloomRuntime + SSE 对话 / 历史",
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

    message = body.message.strip()
    if not message:
        raise HTTPException(status_code=400, detail="message 不能为空")

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

    if body.stream:
        return StreamingResponse(
            _stream_chat(
                message,
                session_id=session_id,
                client_ctx=client_ctx,
                present_mode=present_mode,
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
        client_ctx=client_ctx,
        present_mode=present_mode,
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
) -> AsyncIterator[str]:
    assert _runtime is not None
    async with _run_lock:
        try:
            trigger = Message(role=Role.USER, content=message)
            final: RunResult | None = None
            async for item in _runtime.run_stream(
                trigger,
                session_id=session_id,
                present_mode=present_mode,
                bearer_token=client_ctx["bearer_token"],
            ):
                if isinstance(item, RunResult):
                    final = item
                    continue
                mapped = event_to_sse(item)
                if mapped is not None:
                    name, payload = mapped
                    payload["session_id"] = session_id
                    yield format_sse(name, payload)
                if isinstance(item, ErrorEvent) and not item.recoverable:
                    return

            if final is not None:
                name, payload = turn_complete_payload(
                    route=final.present_mode,
                    final_message=(final.content or "").strip(),
                    session_id=session_id,
                    reason="" if final.ok else (final.error or ""),
                )
                yield format_sse(name, payload)
        except Exception as exc:
            yield format_sse(
                "error",
                {"error": str(exc), "session_id": session_id},
            )
        finally:
            clear_request_context()


async def _run_chat_once(
    message: str,
    *,
    session_id: str,
    client_ctx: ClientHeaderContext,
    present_mode: PresentMode,
) -> ChatResponse:
    assert _runtime is not None
    async with _run_lock:
        try:
            trigger = Message(role=Role.USER, content=message)
            final: RunResult | None = None
            async for item in _runtime.run_stream(
                trigger,
                session_id=session_id,
                present_mode=present_mode,
                bearer_token=client_ctx["bearer_token"],
            ):
                if isinstance(item, RunResult):
                    final = item
                elif isinstance(item, ErrorEvent) and not item.recoverable:
                    raise HTTPException(status_code=500, detail=item.error)
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
