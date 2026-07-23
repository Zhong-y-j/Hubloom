"""Agent 内部事件 → AG-UI 出站 SSE（官方 ``ag-ui-protocol``）。

使用 ``ag_ui.core`` 事件模型 + ``ag_ui.encoder.EventEncoder`` 编码。
不改变 Think / Present / Respond 业务逻辑。

兼容：``examples/chat/app.py`` 仍可调用 ``event_to_sse`` / ``format_sse`` /
``turn_complete_payload``（经 ``agent.sse`` 再导出）。
"""

from __future__ import annotations

import json
import uuid
from typing import Any

from ag_ui.core import (
    CustomEvent,
    EventType,
    RunErrorEvent,
    RunFinishedEvent,
    RunStartedEvent,
    TextMessageContentEvent,
    ThinkingTextMessageContentEvent,
    ToolCallArgsEvent,
    ToolCallEndEvent,
    ToolCallResultEvent,
    ToolCallStartEvent,
)
from ag_ui.core.events import BaseEvent
from ag_ui.encoder import EventEncoder

from agent.events import (
    A2uiMessagesEvent,
    AgentEvent,
    ErrorEvent,
    FinalAnswerDeltaEvent,
    PhaseEvent,
    RemoteProcessEvent,
    TextDeltaEvent,
    ThoughtDeltaEvent,
    ToolCallEvent,
    ToolResultEvent,
)

# app.py 会往 payload 里塞 session_id；工具三段式用此键挂 follow-up
_HUBLOOM_PAYLOAD_KEYS = frozenset({"session_id", "_agui_followups"})

_ENCODER = EventEncoder()

_TYPE_TO_CLS: dict[str, type[BaseEvent]] = {
    EventType.TEXT_MESSAGE_CONTENT.value: TextMessageContentEvent,
    EventType.THINKING_TEXT_MESSAGE_CONTENT.value: ThinkingTextMessageContentEvent,
    EventType.TOOL_CALL_START.value: ToolCallStartEvent,
    EventType.TOOL_CALL_ARGS.value: ToolCallArgsEvent,
    EventType.TOOL_CALL_END.value: ToolCallEndEvent,
    EventType.TOOL_CALL_RESULT.value: ToolCallResultEvent,
    EventType.CUSTOM.value: CustomEvent,
    EventType.RUN_STARTED.value: RunStartedEvent,
    EventType.RUN_FINISHED.value: RunFinishedEvent,
    EventType.RUN_ERROR.value: RunErrorEvent,
}


def compact_tool_result(result: str, max_len: int = 4000) -> str:
    text = (result or "").strip()
    if len(text) <= max_len:
        return text
    return text[: max_len - 3] + "..."


def _new_id(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:12]}"


def _dump(event: BaseEvent) -> dict[str, Any]:
    return event.model_dump(by_alias=True, exclude_none=True, mode="json")


def _hydrate(type_name: str, data: dict[str, Any]) -> BaseEvent:
    cls = _TYPE_TO_CLS.get(type_name)
    if cls is None:
        raise ValueError(f"不支持的 AG-UI 事件类型: {type_name!r}")
    # 去掉 Hubloom / 编码附属字段，再交给官方模型校验
    clean = {k: v for k, v in data.items() if k not in _HUBLOOM_PAYLOAD_KEYS}
    return cls.model_validate(clean)


def _pack(event: BaseEvent, *followups: BaseEvent) -> tuple[str, dict[str, Any]]:
    payload = _dump(event)
    type_name = str(payload.get("type") or "")
    if followups:
        payload["_agui_followups"] = [_dump(e) for e in followups]
    return type_name, payload


def event_to_sse(ev: AgentEvent) -> tuple[str, dict[str, Any]] | None:
    """``AgentEvent`` → ``(agui_type, payload)``；``None`` 表示不推送。

    文本增量暂映射为 ``TEXT_MESSAGE_CONTENT``（START/END 由下一步在 app 流式会话补全）。
    工具调用会附带 ARGS + END（经 ``format_sse`` 一次编出多段 SSE）。
    """
    mapped = _to_agui_events(ev)
    if not mapped:
        return None
    head, *rest = mapped
    return _pack(head, *rest)


def _to_agui_events(ev: AgentEvent) -> list[BaseEvent]:
    if isinstance(ev, TextDeltaEvent):
        return [_text_content(ev.delta, source="markdown")]

    if isinstance(ev, FinalAnswerDeltaEvent):
        source = (ev.source or "markdown").strip() or "markdown"
        if source == "a2ui":
            return [
                CustomEvent(
                    type=EventType.CUSTOM,
                    name="hubloom.a2ui_text",
                    value={"delta": ev.delta},
                )
            ]
        return [_text_content(ev.delta, source=source)]

    if isinstance(ev, A2uiMessagesEvent):
        value: dict[str, Any] = {"messages": ev.messages}
        if ev.replace:
            value["replace"] = True
        return [
            CustomEvent(
                type=EventType.CUSTOM,
                name="hubloom.a2ui",
                value=value,
            )
        ]

    if isinstance(ev, ThoughtDeltaEvent):
        return [
            ThinkingTextMessageContentEvent(
                type=EventType.THINKING_TEXT_MESSAGE_CONTENT,
                delta=ev.delta,
                raw_event={"phase": ev.phase},
            )
        ]

    if isinstance(ev, PhaseEvent):
        return [
            CustomEvent(
                type=EventType.CUSTOM,
                name="hubloom.phase",
                value={"phase": ev.phase, "route": ev.route},
            )
        ]

    if isinstance(ev, ToolCallEvent):
        call_id = ev.call_id
        return [
            ToolCallStartEvent(
                type=EventType.TOOL_CALL_START,
                tool_call_id=call_id,
                tool_call_name=ev.tool_name,
            ),
            ToolCallArgsEvent(
                type=EventType.TOOL_CALL_ARGS,
                tool_call_id=call_id,
                delta=json.dumps(ev.args or {}, ensure_ascii=False),
            ),
            ToolCallEndEvent(
                type=EventType.TOOL_CALL_END,
                tool_call_id=call_id,
            ),
        ]

    if isinstance(ev, ToolResultEvent):
        return [
            ToolCallResultEvent(
                type=EventType.TOOL_CALL_RESULT,
                tool_call_id=ev.call_id,
                message_id=_new_id("msg"),
                content=compact_tool_result(ev.result, max_len=4000),
                role="tool",
                raw_event={
                    "isError": bool(ev.is_error),
                    "toolCallName": ev.tool_name,
                },
            )
        ]

    if isinstance(ev, RemoteProcessEvent):
        return [
            CustomEvent(
                type=EventType.CUSTOM,
                name="hubloom.remote_delta",
                value={
                    "call_id": ev.call_id,
                    "agent_id": ev.agent_id,
                    "channel": ev.channel,
                    "delta": ev.delta,
                    "status": ev.status,
                },
            )
        ]

    if isinstance(ev, ErrorEvent):
        return [
            RunErrorEvent(
                type=EventType.RUN_ERROR,
                message=ev.error,
                code="recoverable" if ev.recoverable else None,
            )
        ]

    return []


def _text_content(delta: str, *, source: str) -> TextMessageContentEvent:
    return TextMessageContentEvent(
        type=EventType.TEXT_MESSAGE_CONTENT,
        message_id=_new_id("msg"),
        delta=delta,
        raw_event={"source": source},
    )


def format_sse(event_name: str, payload: dict[str, Any]) -> str:
    """用官方 ``EventEncoder`` 编成 AG-UI SSE（可含 follow-up 多段）。"""
    body = dict(payload or {})
    followups = body.pop("_agui_followups", None) or []
    body.pop("session_id", None)
    if "type" not in body:
        body["type"] = event_name

    chunks = [_ENCODER.encode(_hydrate(str(body["type"]), body))]
    for item in followups:
        if not isinstance(item, dict):
            continue
        fol = dict(item)
        fol.pop("session_id", None)
        type_name = str(fol.get("type") or "")
        chunks.append(_ENCODER.encode(_hydrate(type_name, fol)))
    return "".join(chunks)


def turn_complete_payload(
    *,
    route: str,
    final_message: str,
    session_id: str,
    reason: str = "",
    answer_parts: list[dict[str, Any]] | None = None,
) -> tuple[str, dict[str, Any]]:
    """一轮结束 → 官方 ``RunFinishedEvent``。"""
    result: dict[str, Any] = {
        "route": route,
        "final_message": final_message,
        "session_id": session_id,
        "reason": reason,
    }
    if answer_parts:
        result["answer_parts"] = answer_parts
    event = RunFinishedEvent(
        type=EventType.RUN_FINISHED,
        thread_id=session_id,
        run_id=_new_id("run"),
        result=result,
    )
    return _pack(event)


def run_started_payload(
    *,
    session_id: str,
    run_id: str | None = None,
) -> tuple[str, dict[str, Any]]:
    """供下一步在 ``app.py`` 流式开头调用。"""
    rid = (run_id or "").strip() or _new_id("run")
    event = RunStartedEvent(
        type=EventType.RUN_STARTED,
        thread_id=session_id,
        run_id=rid,
    )
    return _pack(event)


# ---------------------------------------------------------------------------
# 下一步还要改哪里
# ---------------------------------------------------------------------------
#
# 1. examples/chat/app.py — RUN_STARTED；文本 START/END 会话态
# 2. examples/chat/web — 按 type 解析；CUSTOM hubloom.a2ui → 面板
# 3. docs/Hubloom-SSE契约.md — 重写事件表
# 4. 内部 agent/events.py / run.py 可暂不动
