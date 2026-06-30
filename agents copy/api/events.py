"""Hub 事件 → JSON（SSE / 非流式 API）。"""

from __future__ import annotations

import json
from typing import Any

from agents.core.events import (
    AgentEvent,
    ErrorEvent,
    HubPhaseEvent,
    HubTurnCompleteEvent,
    IntentOutcomeEvent,
    TextDeltaEvent,
    ToolCallEvent,
    ToolResultEvent,
)
from agents.scripts.hub_io import compact_tool_result


def _intent_dict(intent: Any) -> dict[str, Any] | None:
    if intent is None:
        return None
    to_dict = getattr(intent, "to_dict", None)
    if callable(to_dict):
        return to_dict()
    return None


def event_to_sse(ev: AgentEvent) -> tuple[str, dict[str, Any]] | None:
    """返回 (event_name, payload)；None 表示不对外推送。"""
    if isinstance(ev, TextDeltaEvent):
        return "text_delta", {"delta": ev.delta}
    if isinstance(ev, ToolCallEvent):
        return "tool_call", {
            "call_id": ev.call_id,
            "tool_name": ev.tool_name,
            "args": ev.args,
        }
    if isinstance(ev, ToolResultEvent):
        return "tool_result", {
            "call_id": ev.call_id,
            "tool_name": ev.tool_name,
            "result": compact_tool_result(ev.result, max_len=4000),
            "is_error": ev.is_error,
        }
    if isinstance(ev, HubPhaseEvent):
        return "phase", {"phase": ev.phase}
    if isinstance(ev, IntentOutcomeEvent):
        return "intent", {
            "is_clear": ev.is_clear,
            "should_invoke_plan": ev.should_invoke_plan,
            "intent": _intent_dict(ev.intent),
        }
    if isinstance(ev, HubTurnCompleteEvent):
        final = (ev.final_user_message or ev.user_reply or "").strip()
        return "turn_complete", {
            "route": ev.route,
            "final_message": final,
            "user_reply": ev.user_reply,
            "deliverable": ev.deliverable,
            "delivery_summary": ev.delivery_summary,
            "intent": _intent_dict(ev.intent),
        }
    if isinstance(ev, ErrorEvent):
        return "error", {"error": ev.error}
    return None


def format_sse(event_name: str, payload: dict[str, Any]) -> str:
    data = json.dumps(payload, ensure_ascii=False)
    return f"event: {event_name}\ndata: {data}\n\n"
