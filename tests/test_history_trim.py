"""会话历史成组裁剪：不拆断 assistant(tool_calls)+tool。"""

from __future__ import annotations

from core.models import Message, Role, ToolCall
from memory.context import (
    ContextAssembler,
    estimate_message_tokens,
    group_conversation_messages,
    trim_conversation_history,
)


def _tc(id_: str, name: str = "call_tool") -> ToolCall:
    return ToolCall(id=id_, name=name, arguments={"x": 1})


def _assistant_tools(*ids: str, content: str = "thinking") -> Message:
    return Message(
        role=Role.ASSISTANT,
        content=content,
        tool_calls=[_tc(i) for i in ids],
    )


def _tool(id_: str, body: str = "ok") -> Message:
    return Message(role=Role.TOOL, content=body, tool_call_id=id_)


def test_group_keeps_tool_chain_together() -> None:
    msgs = [
        Message(role=Role.USER, content="u1"),
        _assistant_tools("a", "b"),
        _tool("a", "ra"),
        _tool("b", "rb"),
        Message(role=Role.ASSISTANT, content="done"),
    ]
    groups = group_conversation_messages(msgs)
    assert len(groups) == 3
    assert [m.role for m in groups[1]] == [Role.ASSISTANT, Role.TOOL, Role.TOOL]


def test_trim_never_leaves_orphan_tool_calls() -> None:
    # 构造：前面有小消息，中间有大 tool 链，后面有用户问句
    big = "结果" * 4000
    msgs = [
        Message(role=Role.USER, content="早先问题"),
        Message(role=Role.ASSISTANT, content="早先回答"),
        Message(role=Role.USER, content="查列表"),
        _assistant_tools("t1", content="要调工具"),
        _tool("t1", big),
        Message(role=Role.ASSISTANT, content="列表如下…"),
        Message(role=Role.USER, content="看详情"),
    ]
    # 预算只够最近几条小消息，逼出「若按条裁会丢掉 tool、留下 tool_calls」的场景
    small_budget = (
        estimate_message_tokens(msgs[-1])
        + estimate_message_tokens(msgs[-2])
        + estimate_message_tokens(msgs[-3])
        + 20
    )
    trimmed = trim_conversation_history(msgs, max_tokens=small_budget)

    # 不应出现：assistant 带 tool_calls 却无完整 tool 回包
    i = 0
    while i < len(trimmed):
        m = trimmed[i]
        if m.role == Role.ASSISTANT and m.tool_calls:
            needed = {tc.id for tc in m.tool_calls if tc.id}
            j = i + 1
            while j < len(trimmed) and trimmed[j].role == Role.TOOL:
                needed.discard(trimmed[j].tool_call_id or "")
                j += 1
            assert not needed, f"incomplete tool chain after trim: {needed}"
            i = j
        else:
            assert m.role != Role.TOOL or (
                i > 0 and trimmed[i - 1].role == Role.ASSISTANT
            )
            i += 1

    # 最近用户问题应尽量保留
    assert any(m.role == Role.USER and "详情" in str(m.content) for m in trimmed)


def test_trim_drops_incomplete_chain() -> None:
    msgs = [
        Message(role=Role.USER, content="q"),
        _assistant_tools("missing"),
        # 故意不给 tool 回包
        Message(role=Role.ASSISTANT, content="继续说"),
    ]
    trimmed = trim_conversation_history(msgs, max_tokens=50_000)
    assert all(not (m.role == Role.ASSISTANT and m.tool_calls) for m in trimmed)
    assert any(m.content == "继续说" for m in trimmed)


def test_assembler_trims_history_not_system() -> None:
    system = "SYSTEM_PROMPT_" + ("规则" * 50)
    big = "工具回包" * 3000
    histories = [
        Message(role=Role.USER, content="旧问"),
        _assistant_tools("x"),
        _tool("x", big),
        Message(role=Role.ASSISTANT, content="旧答"),
        Message(role=Role.USER, content="新问"),
    ]
    asm = ContextAssembler(max_tokens=800)
    out = asm.assemble(
        system_prompt=system,
        histories=histories,
        current_task="",
    )
    assert out[0].role == Role.SYSTEM
    assert system[:20] in str(out[0].content)

    # 历史侧不成半截 tool 链
    for i, m in enumerate(out[1:]):
        if m.role == Role.ASSISTANT and m.tool_calls:
            needed = {tc.id for tc in m.tool_calls if tc.id}
            for fol in out[i + 2 :]:
                if fol.role != Role.TOOL:
                    break
                needed.discard(fol.tool_call_id or "")
            assert not needed
