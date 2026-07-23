"""ChatRequest action 校验与 AG-UI tool 消息翻译。"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from agent.turn_state import TurnStateStore, new_tool_call_id
from core.models import Role
from examples.chat.action_format import (
    A2UI_ACTION_TOOL_NAME,
    action_to_tool_messages,
    format_action_trigger,
)
from examples.chat.schemas import ChatAction, ChatRequest


def test_chat_request_message_xor_action() -> None:
    ok = ChatRequest(message="你好", stream=True)
    assert ok.message == "你好"
    assert ok.action is None

    with pytest.raises(ValidationError):
        ChatRequest(stream=True)

    with pytest.raises(ValidationError):
        ChatRequest(
            message="hi",
            action=ChatAction(type="submit", name="x"),
            run_id="run-1",
        )

    with pytest.raises(ValidationError):
        ChatRequest(
            action=ChatAction(type="submit", name="x"),
        )


def test_chat_request_action_requires_run_id() -> None:
    req = ChatRequest(
        action=ChatAction(
            type="submit",
            name="confirm_add",
            payload={"name": "阳光"},
            tool_call_id="tc-abc",
        ),
        run_id="run-abc",
    )
    assert req.message is None
    assert req.action is not None
    assert req.action.name == "confirm_add"
    assert req.action.tool_call_id == "tc-abc"
    assert req.run_id == "run-abc"


def test_format_action_trigger_keeps_a2ui_line() -> None:
    text = format_action_trigger(
        ChatAction(
            type="submit",
            name="confirm_add_community",
            payload={"name": "阳光花园", "address": "路 1 号"},
        )
    )
    assert "【人机动作 · submit" in text
    assert "[A2UI:confirm_add_community]" in text
    assert "name: 阳光花园" in text

    cancel = format_action_trigger(
        ChatAction(type="cancel", name="cancel_form")
    )
    assert "cancel" in cancel
    assert "(用户取消当前表单)" in cancel


def test_action_to_tool_messages() -> None:
    action = ChatAction(
        type="submit",
        name="confirm_add",
        payload={"name": "A"},
    )
    tid = "tc-fixed"
    msgs = action_to_tool_messages(
        action, tool_call_id=tid, source_run_id="run-1"
    )
    assert len(msgs) == 2
    stub, tool = msgs
    assert stub.role == Role.ASSISTANT
    assert stub.tool_calls is not None
    assert stub.tool_calls[0].id == tid
    assert stub.tool_calls[0].name == A2UI_ACTION_TOOL_NAME
    assert tool.role == Role.TOOL
    assert tool.tool_call_id == tid
    assert tool.name == A2UI_ACTION_TOOL_NAME
    assert "[A2UI:confirm_add]" in str(tool.content)


def test_resolve_then_tool_messages_for_action_path() -> None:
    """waiting 带 tool_call_id → resolve → 译成 tool 消息对。"""
    store = TurnStateStore()
    sid = "s1"
    form_run = store.begin_run(sid)
    tcid = new_tool_call_id()
    store.mark_waiting(sid, form_run, meta={"tool_call_id": tcid})
    resolved = store.resolve_action(sid, form_run, resolution="submit")
    assert resolved.meta["tool_call_id"] == tcid
    assert store.get_pending(sid) is None
    msgs = action_to_tool_messages(
        ChatAction(type="submit", name="ok", tool_call_id=tcid),
        tool_call_id=tcid,
        source_run_id=form_run,
    )
    assert msgs[1].tool_call_id == tcid
    cont = store.begin_run(sid)
    assert cont != form_run
