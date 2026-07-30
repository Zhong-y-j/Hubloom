"""Agent Step2：Evidence Journal + step/run_complete（不经 Runtime）。

用法::

    PYTHONPATH=src .venv/bin/python tests/test_agent_v2_step2.py
"""

from __future__ import annotations

import asyncio
import tempfile
from collections.abc import AsyncIterator, Sequence
from pathlib import Path
from typing import Any

from agent.actions import CONTROL_FINISH, parse_decide_output, ActionParseError
from agent.assemble import assemble_messages
from agent.evidence import EvidenceJournal
from agent.events import (
    RunCompleteEvent,
    StepEvent,
    ToolResultEvent,
)
from agent.run import RunResult, run_stream
from core.models import LLMOutput, Message, Role, StopReason, ToolCall
from core.provider import LLMProvider, LLMStreamEvent, StreamEndEvent
from memory import create_memory_manager
from tools.base import BaseTool
from tools.registry import ToolRegistry
from tools.runner import ToolRunner


class ScriptedLLM(LLMProvider):
    def __init__(self, outputs: Sequence[LLMOutput]) -> None:
        self._outputs = list(outputs)
        self._i = 0
        self.last_messages: list[Message] = []

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
        raise RuntimeError("ScriptedLLM: no output")

    async def generate_stream(
        self,
        messages: list[Message],
        tools: list[dict] | None = None,
        stop: list[str] | None = None,
        **kwargs: Any,
    ) -> AsyncIterator[LLMStreamEvent]:
        del tools, stop, kwargs
        self.last_messages = list(messages)
        if self._i >= len(self._outputs):
            raise RuntimeError("ScriptedLLM: no more scripted outputs")
        out = self._outputs[self._i]
        self._i += 1
        yield StreamEndEvent(out)


class EchoTool(BaseTool):
    name = "echo_pet"
    description = "测试用：回显 name"
    parameters = {
        "type": "object",
        "properties": {"name": {"type": "string"}},
        "required": ["name"],
    }

    async def execute(self, **kwargs: Any) -> str:
        return f"ok:{kwargs.get('name', '')}"


def _tmp_memory():
    tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    tmp.close()
    path = tmp.name
    mem = create_memory_manager(
        namespace="agent-step2-test",
        db_path=path,
        vector_backend="none",
        graph_backend="none",
    )
    return mem, path


def test_mutex_still() -> None:
    try:
        parse_decide_output(
            content="",
            reasoning_content="",
            tool_calls=[
                ToolCall(id="a", name="call_api", arguments={}),
                ToolCall(
                    id="b",
                    name=CONTROL_FINISH,
                    arguments={"summary": "x"},
                ),
            ],
        )
        raise AssertionError("expected ActionParseError")
    except ActionParseError:
        print("ok: mutex mix rejected")


def test_journal_unit() -> None:
    j = EvidenceJournal(run_id="testrun")
    e1 = j.append(step=1, kind="observation", summary="ok:小花", tool_name="echo_pet")
    e2 = j.append(step=2, kind="finish", summary="已登记")
    assert e1.id == "testrun:1"
    assert e2.id == "testrun:2"
    block = j.summary_for_prompt()
    assert "testrun:1" in block and "echo_pet" in block
    assert "Evidence Journal" in block
    print("ok: journal unit + summary")


async def test_loop_journal() -> None:
    registry = ToolRegistry.from_tools([EchoTool()])
    runner = ToolRunner(registry)
    tools = registry.list_definitions()
    system = "step2 test system"
    journal = EvidenceJournal(run_id="loopdemo")

    mem, path = _tmp_memory()
    try:
        llm = ScriptedLLM(
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
                            id="f2",
                            name=CONTROL_FINISH,
                            arguments={
                                "summary": "已登记宠物小花。",
                                "cites": ["loopdemo:1"],
                            },
                        )
                    ],
                    stop_reason=StopReason.TOOL_CALLS,
                ),
            ]
        )
        saw_step_act = False
        saw_step_finish = False
        saw_tool_jid = False
        complete: RunCompleteEvent | None = None
        result: RunResult | None = None

        async for item in run_stream(
            llm=llm,
            memory=mem,
            runner=runner,
            tools=tools,
            trigger=Message(role=Role.USER, content="加宠物小花"),
            system_before=system,
            system_after=system,
            max_rounds=4,
            journal=journal,
        ):
            if isinstance(item, ToolResultEvent):
                assert item.journal_id.startswith("loopdemo:")
                saw_tool_jid = True
            if isinstance(item, StepEvent):
                if item.action == "act":
                    saw_step_act = True
                    assert item.journal_ids and item.journal_ids[0].startswith(
                        "loopdemo:"
                    )
                if item.action == "finish":
                    saw_step_finish = True
                    assert item.journal_ids
            if isinstance(item, RunCompleteEvent):
                complete = item
            if isinstance(item, RunResult):
                result = item

        assert saw_step_act and saw_step_finish and saw_tool_jid
        assert complete is not None and result is not None
        assert complete.journal_run_id == "loopdemo"
        assert "loopdemo:1" in complete.evidence_ids
        assert result.journal_run_id == "loopdemo"
        assert result.cites == ["loopdemo:1"]
        assert result.status == "completed"

        # 第二轮 Decide 时应已把 Journal 摘要装进 messages
        assert any(
            "Evidence Journal" in (m.content or "")
            and "loopdemo:1" in (m.content or "")
            for m in llm.last_messages
            if m.role == Role.SYSTEM
        ), "assemble 未注入 Journal 摘要"
        print("ok: loop act→finish 带 journal id / step / run_complete")
    finally:
        Path(path).unlink(missing_ok=True)


async def test_assemble_journal_block() -> None:
    mem, path = _tmp_memory()
    try:
        j = EvidenceJournal(run_id="asm")
        j.append(step=1, kind="observation", summary="seen", tool_name="echo_pet")
        msgs = await assemble_messages(
            mem,
            system_prompt="sys",
            turn_messages=[Message(role=Role.USER, content="hi")],
            journal=j,
        )
        systems = [m for m in msgs if m.role == Role.SYSTEM]
        assert len(systems) >= 2
        assert any("asm:1" in (m.content or "") for m in systems)
        print("ok: assemble 注入 journal system 块")
    finally:
        Path(path).unlink(missing_ok=True)


def main() -> None:
    test_mutex_still()
    test_journal_unit()
    asyncio.run(test_assemble_journal_block())
    asyncio.run(test_loop_journal())
    print("\nstep2: 全部通过")


if __name__ == "__main__":
    main()
