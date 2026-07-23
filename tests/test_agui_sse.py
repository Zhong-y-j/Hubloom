"""agui_sse：AgentEvent → 官方 AG-UI SSE 编码。"""

from __future__ import annotations

import json
import re

from agent.agui_sse import (
    compact_tool_result,
    event_to_sse,
    format_sse,
    run_started_payload,
    turn_complete_payload,
)
from agent.events import (
    A2uiMessagesEvent,
    ErrorEvent,
    FinalAnswerDeltaEvent,
    PhaseEvent,
    RemoteProcessEvent,
    TextDeltaEvent,
    ThoughtDeltaEvent,
    ToolCallEvent,
    ToolResultEvent,
)
from agent.sse import event_to_sse as event_to_sse_compat


def _sse_payloads(sse: str) -> list[dict]:
    """解析 ``data: {...}\\n\\n`` 多段 SSE，返回 JSON 对象列表。"""
    out: list[dict] = []
    for block in re.split(r"\n\n+", sse.strip()):
        line = block.strip()
        if not line.startswith("data:"):
            continue
        raw = line[len("data:") :].strip()
        out.append(json.loads(raw))
    return out


def test_text_delta_maps_to_text_message_content() -> None:
    mapped = event_to_sse(TextDeltaEvent(delta="你好"))
    assert mapped is not None
    name, payload = mapped
    assert name == "TEXT_MESSAGE_CONTENT"
    assert payload["type"] == "TEXT_MESSAGE_CONTENT"
    assert payload["delta"] == "你好"

    frames = _sse_payloads(format_sse(name, {**payload, "session_id": "s1"}))
    assert len(frames) == 1
    assert frames[0]["type"] == "TEXT_MESSAGE_CONTENT"
    assert frames[0]["delta"] == "你好"
    assert "session_id" not in frames[0]


def test_final_answer_a2ui_text_is_custom() -> None:
    mapped = event_to_sse(
        FinalAnswerDeltaEvent(delta="请填写", source="a2ui")
    )
    assert mapped is not None
    name, payload = mapped
    assert name == "CUSTOM"
    assert payload["name"] == "hubloom.a2ui_text"
    assert payload["value"]["delta"] == "请填写"


def test_a2ui_messages_custom_event() -> None:
    mapped = event_to_sse(
        A2uiMessagesEvent(messages=[{"createSurface": {"surfaceId": "x"}}], replace=True)
    )
    assert mapped is not None
    name, payload = mapped
    assert name == "CUSTOM"
    assert payload["name"] == "hubloom.a2ui"
    assert payload["value"]["replace"] is True
    assert payload["value"]["messages"][0]["createSurface"]["surfaceId"] == "x"


def test_thought_delta_thinking_content() -> None:
    mapped = event_to_sse(ThoughtDeltaEvent(phase="thinking", delta="分析中"))
    assert mapped is not None
    name, payload = mapped
    assert name == "THINKING_TEXT_MESSAGE_CONTENT"
    frames = _sse_payloads(format_sse(name, payload))
    assert frames[0]["type"] == "THINKING_TEXT_MESSAGE_CONTENT"
    assert frames[0]["delta"] == "分析中"
    assert frames[0]["rawEvent"]["phase"] == "thinking"


def test_phase_and_remote_are_custom() -> None:
    phase = event_to_sse(PhaseEvent(phase="replying", route="agent"))
    assert phase is not None
    assert phase[0] == "CUSTOM"
    assert phase[1]["name"] == "hubloom.phase"

    remote = event_to_sse(
        RemoteProcessEvent(
            call_id="c1",
            agent_id="a2",
            channel="trace",
            delta="...",
            status="working",
        )
    )
    assert remote is not None
    assert remote[1]["name"] == "hubloom.remote_delta"


def test_tool_call_emits_start_args_end() -> None:
    mapped = event_to_sse(
        ToolCallEvent(call_id="call-1", tool_name="list_api", args={"tag": "Demo"})
    )
    assert mapped is not None
    name, payload = mapped
    assert name == "TOOL_CALL_START"
    assert "_agui_followups" in payload

    frames = _sse_payloads(format_sse(name, payload))
    assert [f["type"] for f in frames] == [
        "TOOL_CALL_START",
        "TOOL_CALL_ARGS",
        "TOOL_CALL_END",
    ]
    assert frames[0]["toolCallId"] == "call-1"
    assert frames[0]["toolCallName"] == "list_api"
    assert json.loads(frames[1]["delta"]) == {"tag": "Demo"}
    assert frames[2]["toolCallId"] == "call-1"


def test_tool_result_and_error() -> None:
    result = event_to_sse(
        ToolResultEvent(
            call_id="call-1",
            tool_name="list_api",
            result='{"ok": true}',
            is_error=False,
        )
    )
    assert result is not None
    assert result[0] == "TOOL_CALL_RESULT"
    frames = _sse_payloads(format_sse(*result))
    assert frames[0]["type"] == "TOOL_CALL_RESULT"
    assert frames[0]["content"] == '{"ok": true}'

    err = event_to_sse(ErrorEvent(error="失败", recoverable=True))
    assert err is not None
    assert err[0] == "RUN_ERROR"
    frames = _sse_payloads(format_sse(*err))
    assert frames[0]["message"] == "失败"
    assert frames[0]["code"] == "recoverable"


def test_run_started_and_finished() -> None:
    started = run_started_payload(session_id="thread-1", run_id="run-fixed")
    assert started[0] == "RUN_STARTED"
    frames = _sse_payloads(format_sse(*started))
    assert frames[0]["threadId"] == "thread-1"
    assert frames[0]["runId"] == "run-fixed"

    finished = turn_complete_payload(
        route="auto",
        final_message="完成",
        session_id="thread-1",
        reason="",
        answer_parts=[{"type": "text", "text": "完成"}],
    )
    assert finished[0] == "RUN_FINISHED"
    frames = _sse_payloads(format_sse(*finished))
    assert frames[0]["type"] == "RUN_FINISHED"
    assert frames[0]["result"]["final_message"] == "完成"
    assert frames[0]["result"]["answer_parts"][0]["text"] == "完成"


def test_compact_tool_result() -> None:
    assert compact_tool_result("short") == "short"
    long = "x" * 50
    out = compact_tool_result(long, max_len=20)
    assert len(out) == 20
    assert out.endswith("...")


def test_agent_sse_compat_reexport() -> None:
    """``agent.sse`` 仍应导出同一实现。"""
    a = event_to_sse(TextDeltaEvent(delta="x"))
    b = event_to_sse_compat(TextDeltaEvent(delta="x"))
    assert a is not None and b is not None
    assert a[0] == b[0] == "TEXT_MESSAGE_CONTENT"
