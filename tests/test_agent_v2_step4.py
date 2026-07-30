"""Agent Step4：Gate + 最小 Playbook（不经 Runtime）。

用法::

    PYTHONPATH=src .venv/bin/python tests/test_agent_v2_step4.py
"""

from __future__ import annotations

import asyncio
import tempfile
from collections.abc import AsyncIterator, Sequence
from pathlib import Path
from typing import Any

from agent.actions import CONTROL_CONFIRM, CONTROL_FINISH, ActAction, FinishAction
from agent.events import PolicyRejectEvent
from agent.gate import check_action
from agent.policy import (
    Playbook,
    PlaybookProgress,
    RequireStep,
    compile_playbook_from_skills,
    playbook_from_mapping,
)
from agent.run import RunResult, run_stream
from core.models import LLMOutput, Message, Role, StopReason, ToolCall
from core.provider import LLMProvider, LLMStreamEvent, StreamEndEvent
from memory import create_memory_manager
from skill.load import load_skills
from tools.base import BaseTool
from tools.registry import ToolRegistry
from tools.runner import ToolRunner


class ScriptedLLM(LLMProvider):
    def __init__(self, outputs: Sequence[LLMOutput]) -> None:
        self._outputs = list(outputs)
        self._i = 0

    async def generate(
        self,
        messages: list[Message],
        tools: list[dict] | None = None,
        stop: list[str] | None = None,
        **kwargs: Any,
    ) -> LLMOutput:
        async for ev in self.generate_stream(
            messages, tools=tools, stop=stop, **kwargs
        ):
            if isinstance(ev, StreamEndEvent):
                return ev.output
        raise RuntimeError("no output")

    async def generate_stream(
        self,
        messages: list[Message],
        tools: list[dict] | None = None,
        stop: list[str] | None = None,
        **kwargs: Any,
    ) -> AsyncIterator[LLMStreamEvent]:
        del messages, tools, stop, kwargs
        if self._i >= len(self._outputs):
            raise RuntimeError("ScriptedLLM exhausted")
        out = self._outputs[self._i]
        self._i += 1
        yield StreamEndEvent(out)


class EchoTool(BaseTool):
    name = "echo_pet"
    description = "登记宠物"
    parameters = {
        "type": "object",
        "properties": {"name": {"type": "string"}},
        "required": ["name"],
    }

    async def execute(self, **kwargs: Any) -> str:
        return f"ok:{kwargs.get('name', '')}"


class BadTool(BaseTool):
    name = "echo_bad"
    description = "禁止工具"
    parameters = {"type": "object", "properties": {}}

    async def execute(self, **kwargs: Any) -> str:
        return "should-not-run"


def _tmp_memory(ns: str = "agent-step4"):
    tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    tmp.close()
    path = tmp.name
    mem = create_memory_manager(
        namespace=ns,
        db_path=path,
        vector_backend="none",
        graph_backend="none",
    )
    return mem, path


async def _drain(agen) -> tuple[RunResult, list[PolicyRejectEvent]]:
    result: RunResult | None = None
    rejects: list[PolicyRejectEvent] = []
    async for item in agen:
        if isinstance(item, PolicyRejectEvent):
            rejects.append(item)
        if isinstance(item, RunResult):
            result = item
    if result is None:
        raise AssertionError("no RunResult")
    return result, rejects


def test_compile_from_skill_md() -> None:
    root = Path(tempfile.mkdtemp())
    skill_dir = root / "pet-register"
    skill_dir.mkdir()
    (skill_dir / "SKILL.md").write_text(
        """---
name: pet-register
description: 加宠后必须登记
playbook:
  forbid_tools: [echo_bad]
  require_steps:
    - id: register_pet
      tools: [echo_pet]
  confirm_tools: [echo_pet]
---

# body
""",
        encoding="utf-8",
    )
    skills = load_skills(root)
    book = compile_playbook_from_skills(skills)
    assert "echo_bad" in book.forbid_tools
    assert "echo_pet" in book.confirm_tools
    assert book.require_steps[0].id == "register_pet"
    assert "echo_pet" in book.require_steps[0].tools
    print("ok: Skill frontmatter → Playbook")


def test_gate_unit() -> None:
    book = Playbook(
        forbid_tools=frozenset({"echo_bad"}),
        require_steps=(RequireStep(id="register_pet", tools=("echo_pet",)),),
        confirm_tools=frozenset({"echo_pet"}),
    )
    progress = PlaybookProgress(fuse_limit=2)

    v = check_action(
        ActAction(tool_calls=[ToolCall(id="1", name="echo_bad", arguments={})]),
        book,
        progress,
    )
    assert not v.allow and v.code == "forbid_tool"

    progress2 = PlaybookProgress()
    v = check_action(
        FinishAction(summary="done"),
        book,
        progress2,
    )
    assert not v.allow and v.code == "require_steps"

    progress2.mark_tool_success("echo_pet", book)
    v = check_action(FinishAction(summary="done"), book, progress2)
    assert v.allow

    progress3 = PlaybookProgress()
    v = check_action(
        ActAction(
            tool_calls=[ToolCall(id="1", name="echo_pet", arguments={"name": "x"})]
        ),
        book,
        progress3,
    )
    assert not v.allow and v.code == "need_confirm"
    progress3.mark_confirmed()
    v = check_action(
        ActAction(
            tool_calls=[ToolCall(id="1", name="echo_pet", arguments={"name": "x"})]
        ),
        book,
        progress3,
    )
    assert v.allow
    print("ok: gate unit forbid / require / confirm")


async def test_require_steps_loop() -> None:
    """提前 finish 被 Gate 打回，登记后再 finish。"""
    book = playbook_from_mapping(
        {
            "require_steps": [
                {"id": "register_pet", "tools": ["echo_pet"]},
            ]
        },
        source="test",
    )
    registry = ToolRegistry.from_tools([EchoTool()])
    runner = ToolRunner(registry)
    tools = registry.list_definitions()
    system = "step4 require"
    mem, path = _tmp_memory("req")
    try:
        llm = ScriptedLLM(
            [
                # 1) 违规 finish
                LLMOutput(
                    content="",
                    tool_calls=[
                        ToolCall(
                            id="f0",
                            name=CONTROL_FINISH,
                            arguments={"summary": "先随便结束"},
                        )
                    ],
                    stop_reason=StopReason.TOOL_CALLS,
                ),
                # 2) 登记
                LLMOutput(
                    content="",
                    tool_calls=[
                        ToolCall(
                            id="a1",
                            name="echo_pet",
                            arguments={"name": "小花"},
                        )
                    ],
                    stop_reason=StopReason.TOOL_CALLS,
                ),
                # 3) 合法 finish
                LLMOutput(
                    content="",
                    tool_calls=[
                        ToolCall(
                            id="f1",
                            name=CONTROL_FINISH,
                            arguments={"summary": "已登记小花"},
                        )
                    ],
                    stop_reason=StopReason.TOOL_CALLS,
                ),
            ]
        )
        result, rejects = await _drain(
            run_stream(
                llm=llm,
                memory=mem,
                runner=runner,
                tools=tools,
                trigger=Message(role=Role.USER, content="加宠物小花"),
                system_before=system,
                system_after=system,
                playbook=book,
                max_rounds=6,
            )
        )
        assert any(r.code == "require_steps" for r in rejects)
        assert result.status == "completed" and "小花" in result.content
        print("ok: require_steps 打回后登记再 finish")
    finally:
        Path(path).unlink(missing_ok=True)


async def test_forbid_and_fuse() -> None:
    book = Playbook(forbid_tools=frozenset({"echo_bad"}))
    registry = ToolRegistry.from_tools([BadTool(), EchoTool()])
    runner = ToolRunner(registry)
    tools = registry.list_definitions()
    mem, path = _tmp_memory("fuse")
    try:
        llm = ScriptedLLM(
            [
                LLMOutput(
                    content="",
                    tool_calls=[
                        ToolCall(id="b1", name="echo_bad", arguments={})
                    ],
                    stop_reason=StopReason.TOOL_CALLS,
                ),
                LLMOutput(
                    content="",
                    tool_calls=[
                        ToolCall(id="b2", name="echo_bad", arguments={})
                    ],
                    stop_reason=StopReason.TOOL_CALLS,
                ),
            ]
        )
        # Progress fuse_limit default 2 → 第二次熔断
        result, rejects = await _drain(
            run_stream(
                llm=llm,
                memory=mem,
                runner=runner,
                tools=tools,
                trigger=Message(role=Role.USER, content="做坏事"),
                system_before="s",
                system_after="s",
                playbook=book,
                max_rounds=6,
            )
        )
        assert len(rejects) >= 2
        assert rejects[-1].fused
        assert result.status == "failed" and not result.ok
        print("ok: forbid + 同因熔断")
    finally:
        Path(path).unlink(missing_ok=True)


async def test_confirm_then_act() -> None:
    book = Playbook(confirm_tools=frozenset({"echo_pet"}))
    registry = ToolRegistry.from_tools([EchoTool()])
    runner = ToolRunner(registry)
    tools = registry.list_definitions()
    mem, path = _tmp_memory("cfm")
    try:
        llm = ScriptedLLM(
            [
                # 未确认就 act → reject
                LLMOutput(
                    content="",
                    tool_calls=[
                        ToolCall(
                            id="a0",
                            name="echo_pet",
                            arguments={"name": "小花"},
                        )
                    ],
                    stop_reason=StopReason.TOOL_CALLS,
                ),
                # confirm
                LLMOutput(
                    content="",
                    tool_calls=[
                        ToolCall(
                            id="c1",
                            name=CONTROL_CONFIRM,
                            arguments={"prompt": "确认登记小花？"},
                        )
                    ],
                    stop_reason=StopReason.TOOL_CALLS,
                ),
            ]
        )
        # turn_based：confirm 结束 waiting；第二轮再 act+finish
        r1, rejects = await _drain(
            run_stream(
                llm=llm,
                memory=mem,
                runner=runner,
                tools=tools,
                trigger=Message(role=Role.USER, content="加小花"),
                system_before="s",
                system_after="s",
                playbook=book,
                wait_profile="turn_based",
            )
        )
        assert any(r.code == "need_confirm" for r in rejects)
        assert r1.status == "waiting_user" and r1.pending is not None

        llm2 = ScriptedLLM(
            [
                LLMOutput(
                    content="",
                    tool_calls=[
                        ToolCall(
                            id="a1",
                            name="echo_pet",
                            arguments={"name": "小花"},
                        )
                    ],
                    stop_reason=StopReason.TOOL_CALLS,
                ),
                LLMOutput(
                    content="",
                    tool_calls=[
                        ToolCall(
                            id="f1",
                            name=CONTROL_FINISH,
                            arguments={"summary": "已确认并登记"},
                        )
                    ],
                    stop_reason=StopReason.TOOL_CALLS,
                ),
            ]
        )
        r2, _ = await _drain(
            run_stream(
                llm=llm2,
                memory=mem,
                runner=runner,
                tools=tools,
                trigger=Message(role=Role.USER, content="确认"),
                system_before="s",
                system_after="s",
                playbook=book,
                wait_profile="turn_based",
                pending=r1.pending,
            )
        )
        assert r2.status == "completed"
        print("ok: confirm_tools 须确认后再 act")
    finally:
        Path(path).unlink(missing_ok=True)


def main() -> None:
    test_compile_from_skill_md()
    test_gate_unit()
    asyncio.run(test_require_steps_loop())
    asyncio.run(test_forbid_and_fuse())
    asyncio.run(test_confirm_then_act())
    print("\nstep4: 全部通过")


if __name__ == "__main__":
    main()
