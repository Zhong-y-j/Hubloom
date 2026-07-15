"""Hubloom Agent 事件 → JSON（SSE / 非流式 API）。"""

from __future__ import annotations

import json
from typing import Any

from agents.events import (
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
from agents.display import resolve_tool_display_name


def compact_tool_result(result: str, max_len: int = 4000) -> str:
    text = (result or "").strip()
    if len(text) <= max_len:
        return text
    return text[: max_len - 3] + "..."


def event_to_sse(ev: AgentEvent) -> tuple[str, dict[str, Any]] | None:
    """返回 (event_name, payload)；None 表示不对外推送。"""
    if isinstance(ev, TextDeltaEvent):
        return "text_delta", {"delta": ev.delta}
    if isinstance(ev, FinalAnswerDeltaEvent):
        return "text_delta", {"delta": ev.delta}
    if isinstance(ev, ThoughtDeltaEvent):
        return "thought_delta", {"phase": ev.phase, "delta": ev.delta}
    if isinstance(ev, PhaseEvent):
        return "phase", {"phase": ev.phase, "route": ev.route}
    if isinstance(ev, ToolCallEvent):
        return "tool_call", {
            "call_id": ev.call_id,
            "tool_name": resolve_tool_display_name(ev.tool_name, ev.args),
            "args": ev.args,
        }
    if isinstance(ev, ToolResultEvent):
        return "tool_result", {
            "call_id": ev.call_id,
            "tool_name": ev.tool_name,
            "result": compact_tool_result(ev.result, max_len=4000),
            "is_error": ev.is_error,
        }
    if isinstance(ev, RemoteProcessEvent):
        return "remote_delta", {
            "call_id": ev.call_id,
            "agent_id": ev.agent_id,
            "channel": ev.channel,
            "delta": ev.delta,
            "status": ev.status,
        }
    if isinstance(ev, ErrorEvent):
        payload: dict[str, Any] = {"error": ev.error}
        if ev.recoverable:
            payload["recoverable"] = True
        return "error", payload
    return None


def format_sse(event_name: str, payload: dict[str, Any]) -> str:
    data = json.dumps(payload, ensure_ascii=False)
    return f"event: {event_name}\ndata: {data}\n\n"


def turn_complete_payload(
    *,
    route: str,
    final_message: str,
    session_id: str,
    reason: str = "",
) -> tuple[str, dict[str, Any]]:
    return "turn_complete", {
        "route": route,
        "final_message": final_message,
        "session_id": session_id,
        "reason": reason,
    }
