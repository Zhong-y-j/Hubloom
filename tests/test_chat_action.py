"""ChatRequest action 校验与 action 触发文案。"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from examples.chat.action_format import format_action_trigger
from examples.chat.schemas import ChatAction, ChatRequest
from agent.turn_state import TurnStateStore


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
        ),
        run_id="run-abc",
    )
    assert req.message is None
    assert req.action is not None
    assert req.action.name == "confirm_add"
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


def test_resolve_then_new_run_for_action_path() -> None:
    """模拟：校验 resolve 后开新 run，旧 waiting 已清。"""
    store = TurnStateStore()
    sid = "s1"
    form_run = store.begin_run(sid)
    store.mark_waiting(sid, form_run)
    store.resolve_action(sid, form_run, resolution="submit")
    assert store.get_pending(sid) is None
    cont = store.begin_run(sid)
    assert cont != form_run
