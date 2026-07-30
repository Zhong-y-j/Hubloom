"""SSE 编码：简洁 JSON 事件（非 AG-UI / 非 A2UI）。"""

from __future__ import annotations

import json
from typing import Any

from agent.events import (
    AgentEvent,
    AwaitingUserEvent,
    ErrorEvent,
    FinalAnswerEvent,
    PhaseEvent,
    PolicyRejectEvent,
    RunCompleteEvent,
    RunStatsEvent,
    StepEvent,
    TextDeltaEvent,
    ThoughtDeltaEvent,
    ToolCallEvent,
    ToolResultEvent,
)
from agent.run import RunResult


def format_sse(event: str, data: dict[str, Any]) -> str:
    payload = json.dumps(data, ensure_ascii=False, default=str)
    return f"event: {event}\ndata: {payload}\n\n"


def event_to_sse(
    item: AgentEvent | RunResult,
    *,
    session_id: str,
    run_id: str,
) -> str | None:
    """把 Agent 事件编成一条 SSE；无法识别则跳过。"""
    base = {"session_id": session_id, "run_id": run_id}

    if isinstance(item, TextDeltaEvent):
        return format_sse("text_delta", {**base, "delta": item.delta})
    if isinstance(item, ThoughtDeltaEvent):
        return format_sse(
            "thought_delta",
            {**base, "phase": item.phase, "delta": item.delta},
        )
    if isinstance(item, FinalAnswerEvent):
        return format_sse("final_answer", {**base, "content": item.content})
    if isinstance(item, ErrorEvent):
        return format_sse(
            "error",
            {
                **base,
                "error": item.error,
                "recoverable": item.recoverable,
            },
        )
    if isinstance(item, ToolCallEvent):
        return format_sse(
            "tool_call",
            {
                **base,
                "call_id": item.call_id,
                "tool_name": item.tool_name,
                "args": item.args,
            },
        )
    if isinstance(item, ToolResultEvent):
        return format_sse(
            "tool_result",
            {
                **base,
                "call_id": item.call_id,
                "tool_name": item.tool_name,
                "result": item.result,
                "is_error": item.is_error,
                "journal_id": item.journal_id,
            },
        )
    if isinstance(item, StepEvent):
        return format_sse(
            "step",
            {
                **base,
                "step": item.step,
                "action": item.action,
                "journal_ids": item.journal_ids,
            },
        )
    if isinstance(item, PolicyRejectEvent):
        return format_sse(
            "policy_reject",
            {
                **base,
                "code": item.code,
                "reason": item.reason,
                "action": item.action,
                "fused": item.fused,
            },
        )
    if isinstance(item, AwaitingUserEvent):
        return format_sse(
            "awaiting_user",
            {
                **base,
                "await_run_id": item.run_id,
                "await_token": item.await_token,
                "kind": item.kind,
                "prompt": item.prompt,
                "slots": item.slots,
                "payload": item.payload,
            },
        )
    if isinstance(item, PhaseEvent):
        return format_sse(
            "phase",
            {**base, "phase": item.phase, "route": item.route},
        )
    if isinstance(item, RunStatsEvent):
        return format_sse(
            "run_stats",
            {
                **base,
                "steps": item.steps,
                "tool_calls": item.tool_calls,
                "tool_errors": item.tool_errors,
                "elapsed_ms": item.elapsed_ms,
            },
        )
    if isinstance(item, RunCompleteEvent):
        return format_sse(
            "run_complete",
            {
                **base,
                "status": item.status,
                "content": item.content,
                "ok": item.ok,
                "error": item.error,
                "journal_run_id": item.journal_run_id,
                "evidence_ids": item.evidence_ids,
            },
        )
    if isinstance(item, RunResult):
        pending = None
        if item.pending is not None:
            pending = {
                "kind": item.pending.kind,
                "prompt": item.pending.prompt,
                "slots": item.pending.slots,
                "intent": item.pending.intent,
                "from_run_id": item.pending.from_run_id,
            }
        return format_sse(
            "run_result",
            {
                **base,
                "status": item.status,
                "content": item.content,
                "ok": item.ok,
                "error": item.error,
                "journal_run_id": item.journal_run_id,
                "evidence_ids": item.evidence_ids,
                "cites": item.cites,
                "await_token": item.await_token,
                "wait_profile": item.wait_profile,
                "think_rounds": item.think_rounds,
                "tool_calls": item.tool_calls,
                "tool_errors": item.tool_errors,
                "elapsed_ms": item.elapsed_ms,
                "pending": pending,
            },
        )
    return None
