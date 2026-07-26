"""Respond 事实锚定：防止表单提交后编造列表。"""

from __future__ import annotations

from agent.assemble import assemble_respond_markdown, extract_respond_grounding
from core.models import Message, Role
from examples.chat.action_format import format_action_trigger
from examples.chat.schemas import ChatAction


def test_extract_prefer_a2ui_action():
    turn = [
        Message(
            role=Role.TOOL,
            name="call_api",
            content='{"tool":"VehicleKeySmartLocker_GetList","body":{"items":[]}}',
        ),
        Message(
            role=Role.TOOL,
            name="hubloom.a2ui_action",
            content="【人机动作 · submit】\n[A2UI:deleteCabinet]\ncabinetId: abc\nname: YGHY01",
        ),
    ]
    text = extract_respond_grounding(turn)
    assert "本轮事实" in text
    assert "deleteCabinet" in text
    assert text.index("deleteCabinet") < text.index("VehicleKeySmartLocker_GetList")


def test_assemble_respond_includes_grounding():
    msgs = assemble_respond_markdown(
        system_prompt="sys",
        think_content="交 Respond 展示钥匙柜",
        grounding="【本轮事实】\nname: YGHY01",
    )
    assert msgs[-1].role == Role.USER
    assert "交 Respond 展示钥匙柜" in (msgs[-1].content or "")
    assert "YGHY01" in (msgs[-1].content or "")


def test_format_action_trigger_rejects_false_trigger_narrative():
    text = format_action_trigger(
        ChatAction(
            type="submit",
            name="deleteCabinet",
            payload={"cabinetId": "abc", "name": "YGHY01"},
        )
    )
    assert "禁止当作误触发" in text
    assert "call_api" in text
    assert "YGHY01" in text
