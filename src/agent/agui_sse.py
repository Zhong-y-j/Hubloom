"""Agent 内部事件 → AG-UI 出站 SSE（官方 ``ag-ui-protocol``）。

使用 ``ag_ui.core`` 事件模型 + ``ag_ui.encoder.EventEncoder`` 编码。
不改变 Think / Present / Respond 业务逻辑。

兼容：``examples/chat/app.py`` 仍可调用 ``event_to_sse`` / ``format_sse`` /
``turn_complete_payload``（经 ``agent.sse`` 再导出）。

文本流请用 ``AguiStreamEncoder``：同一 ``messageId`` 上
``TEXT_MESSAGE_START → CONTENT* → END``（思考同理）。
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
    TextMessageEndEvent,
    TextMessageStartEvent,
    ThinkingTextMessageContentEvent,
    ThinkingTextMessageEndEvent,
    ThinkingTextMessageStartEvent,
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
_HUBLOOM_PAYLOAD_KEYS = frozenset({"session_id", "run_id", "_agui_followups"})

_ENCODER = EventEncoder()

_TYPE_TO_CLS: dict[str, type[BaseEvent]] = {
    EventType.TEXT_MESSAGE_START.value: TextMessageStartEvent,
    EventType.TEXT_MESSAGE_CONTENT.value: TextMessageContentEvent,
    EventType.TEXT_MESSAGE_END.value: TextMessageEndEvent,
    EventType.THINKING_TEXT_MESSAGE_START.value: ThinkingTextMessageStartEvent,
    EventType.THINKING_TEXT_MESSAGE_CONTENT.value: ThinkingTextMessageContentEvent,
    EventType.THINKING_TEXT_MESSAGE_END.value: ThinkingTextMessageEndEvent,
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

    单事件映射（无会话态）。流式文本请用 ``AguiStreamEncoder``，
    以保证 ``messageId`` 在 START/CONTENT/END 间稳定。
    """
    mapped = _to_agui_events(ev)
    if not mapped:
        return None
    head, *rest = mapped
    return _pack(head, *rest)


def _to_agui_events(ev: AgentEvent) -> list[BaseEvent]:
    if isinstance(ev, TextDeltaEvent):
        return [_text_content(ev.delta, message_id=_new_id("msg"), source="markdown")]

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
        return [_text_content(ev.delta, message_id=_new_id("msg"), source=source)]

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


def _text_content(
    delta: str,
    *,
    message_id: str,
    source: str,
) -> TextMessageContentEvent:
    return TextMessageContentEvent(
        type=EventType.TEXT_MESSAGE_CONTENT,
        message_id=message_id,
        delta=delta,
        raw_event={"source": source},
    )


def format_sse(event_name: str, payload: dict[str, Any]) -> str:
    """用官方 ``EventEncoder`` 编成 AG-UI SSE（可含 follow-up 多段）。"""
    body = dict(payload or {})
    followups = body.pop("_agui_followups", None) or []
    body.pop("session_id", None)
    body.pop("run_id", None)
    if "type" not in body:
        body["type"] = event_name

    chunks = [_ENCODER.encode(_hydrate(str(body["type"]), body))]
    for item in followups:
        if not isinstance(item, dict):
            continue
        fol = dict(item)
        fol.pop("session_id", None)
        fol.pop("run_id", None)
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
    """流式开头 ``RUN_STARTED``。"""
    rid = (run_id or "").strip() or _new_id("run")
    event = RunStartedEvent(
        type=EventType.RUN_STARTED,
        thread_id=session_id,
        run_id=rid,
    )
    return _pack(event)


def a2ui_client_tool_call_sse(
    *,
    tool_call_id: str,
    run_id: str,
    session_id: str | None = None,
) -> str:
    """出 A2UI 表单前：下发客户端工具 ``TOOL_CALL_START/ARGS/END``。"""
    from agent.turn_state import A2UI_ACTION_TOOL_NAME

    tid = (tool_call_id or "").strip()
    if not tid:
        raise ValueError("tool_call_id 不能为空")
    args = json.dumps(
        {"kind": "a2ui", "run_id": (run_id or "").strip()},
        ensure_ascii=False,
    )
    name, payload = _pack(
        ToolCallStartEvent(
            type=EventType.TOOL_CALL_START,
            tool_call_id=tid,
            tool_call_name=A2UI_ACTION_TOOL_NAME,
        ),
        ToolCallArgsEvent(
            type=EventType.TOOL_CALL_ARGS,
            tool_call_id=tid,
            delta=args,
        ),
        ToolCallEndEvent(
            type=EventType.TOOL_CALL_END,
            tool_call_id=tid,
        ),
    )
    if session_id:
        payload["session_id"] = session_id
    return format_sse(name, payload)


def a2ui_client_tool_result_sse(
    *,
    tool_call_id: str,
    content: str,
    session_id: str | None = None,
) -> str:
    """表单 submit/cancel 后：关闭该客户端工具的 ``TOOL_CALL_RESULT``。"""
    from agent.turn_state import A2UI_ACTION_TOOL_NAME

    tid = (tool_call_id or "").strip()
    if not tid:
        raise ValueError("tool_call_id 不能为空")
    event = ToolCallResultEvent(
        type=EventType.TOOL_CALL_RESULT,
        tool_call_id=tid,
        message_id=_new_id("msg"),
        content=compact_tool_result(content, max_len=4000),
        role="tool",
        raw_event={
            "isError": False,
            "toolCallName": A2UI_ACTION_TOOL_NAME,
            "clientTool": True,
        },
    )
    name, payload = _pack(event)
    if session_id:
        payload["session_id"] = session_id
    return format_sse(name, payload)


class AguiStreamEncoder:
    """一轮 run 内的出站编码器：文本 / 思考带 START·END 会话态。"""

    def __init__(self, *, session_id: str = "", run_id: str = "") -> None:
        self.session_id = (session_id or "").strip()
        self.run_id = (run_id or "").strip()
        self._assistant_msg_id: str | None = None
        self._assistant_source: str = "markdown"
        self._thinking_open: bool = False

    def _annotate(self, payload: dict[str, Any]) -> dict[str, Any]:
        if self.session_id:
            payload["session_id"] = self.session_id
        if self.run_id:
            payload["run_id"] = self.run_id
        return payload

    def _emit(self, name: str, payload: dict[str, Any]) -> str:
        return format_sse(name, self._annotate(payload))

    def _close_thinking(self) -> str:
        if not self._thinking_open:
            return ""
        self._thinking_open = False
        name, payload = _pack(
            ThinkingTextMessageEndEvent(type=EventType.THINKING_TEXT_MESSAGE_END)
        )
        return self._emit(name, payload)

    def _close_assistant(self) -> str:
        mid = self._assistant_msg_id
        if not mid:
            return ""
        self._assistant_msg_id = None
        name, payload = _pack(
            TextMessageEndEvent(
                type=EventType.TEXT_MESSAGE_END,
                message_id=mid,
            )
        )
        return self._emit(name, payload)

    def flush(self) -> str:
        """关闭未结束的思考/助手文本（在 RUN_FINISHED / 客户端 TOOL_CALL 前调用）。"""
        return self._close_thinking() + self._close_assistant()

    def feed(self, ev: AgentEvent) -> str:
        """映射一条内部事件为 SSE（可含多帧）。"""
        out = ""

        # 工具调用前结束当前文本/思考，保证 AG-UI 消息边界清晰
        if isinstance(ev, (ToolCallEvent, ToolResultEvent)):
            out += self.flush()

        if isinstance(ev, ThoughtDeltaEvent):
            if self._assistant_msg_id:
                out += self._close_assistant()
            if not self._thinking_open:
                name, payload = _pack(
                    ThinkingTextMessageStartEvent(
                        type=EventType.THINKING_TEXT_MESSAGE_START
                    )
                )
                out += self._emit(name, payload)
                self._thinking_open = True
            name, payload = _pack(
                ThinkingTextMessageContentEvent(
                    type=EventType.THINKING_TEXT_MESSAGE_CONTENT,
                    delta=ev.delta,
                    raw_event={"phase": ev.phase},
                )
            )
            out += self._emit(name, payload)
            return out

        if isinstance(ev, TextDeltaEvent):
            return out + self._feed_assistant_text(ev.delta, source="markdown")

        if isinstance(ev, FinalAnswerDeltaEvent):
            source = (ev.source or "markdown").strip() or "markdown"
            if source == "a2ui":
                # A2UI 侧栏文案仍走 CUSTOM，不打断 markdown 文本会话
                mapped = event_to_sse(ev)
                if mapped is None:
                    return out
                name, payload = mapped
                return out + self._emit(name, payload)
            return out + self._feed_assistant_text(ev.delta, source=source)

        # 其余事件：无会话态包装
        mapped = event_to_sse(ev)
        if mapped is None:
            return out
        name, payload = mapped
        return out + self._emit(name, payload)

    def _feed_assistant_text(self, delta: str, *, source: str) -> str:
        out = self._close_thinking()
        if not delta:
            return out
        if self._assistant_msg_id is None:
            mid = _new_id("msg")
            self._assistant_msg_id = mid
            self._assistant_source = source
            name, payload = _pack(
                TextMessageStartEvent(
                    type=EventType.TEXT_MESSAGE_START,
                    message_id=mid,
                    role="assistant",
                    raw_event={"source": source},
                )
            )
            out += self._emit(name, payload)
        elif source != self._assistant_source:
            # source 切换：结束旧消息，开新消息
            out += self._close_assistant()
            mid = _new_id("msg")
            self._assistant_msg_id = mid
            self._assistant_source = source
            name, payload = _pack(
                TextMessageStartEvent(
                    type=EventType.TEXT_MESSAGE_START,
                    message_id=mid,
                    role="assistant",
                    raw_event={"source": source},
                )
            )
            out += self._emit(name, payload)

        assert self._assistant_msg_id is not None
        name, payload = _pack(
            _text_content(
                delta,
                message_id=self._assistant_msg_id,
                source=source,
            )
        )
        out += self._emit(name, payload)
        return out
