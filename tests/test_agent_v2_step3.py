"""Agent Step3：Wait Profile（不经 Runtime）。

用法::

    PYTHONPATH=src .venv/bin/python tests/test_agent_v2_step3.py
"""

from __future__ import annotations

import asyncio
import tempfile
from collections.abc import AsyncIterator, Sequence
from pathlib import Path
from typing import Any

from agent.actions import CONTROL_ASK, CONTROL_FINISH
from agent.events import AwaitingUserEvent
from agent.run import RunResult, resume_stream, run_stream
from agent.session import InMemorySessionStore, PendingState
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

    def extend(self, outputs: Sequence[LLMOutput]) -> None:
        self._outputs.extend(outputs)

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
    description = "测试用：回显 name"
    parameters = {
        "type": "object",
        "properties": {"name": {"type": "string"}},
        "required": ["name"],
    }

    async def execute(self, **kwargs: Any) -> str:
        return f"ok:{kwargs.get('name', '')}"


def _tmp_memory(ns: str = "agent-step3"):
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


async def _drain(agen) -> RunResult:
    result: RunResult | None = None
    async for item in agen:
        if isinstance(item, RunResult):
            result = item
    if result is None:
        raise AssertionError("no RunResult")
    return result


def _kit():
    registry = ToolRegistry.from_tools([EchoTool()])
    return registry, ToolRunner(registry), registry.list_definitions()


async def test_turn_based_two_rounds() -> None:
    _, runner, tools = _kit()
    store = InMemorySessionStore()
    sid = "tb-1"
    system = "step3 turn_based"
    mem, path = _tmp_memory("tb")
    try:
        llm = ScriptedLLM(
            [
                LLMOutput(
                    content="",
                    tool_calls=[
                        ToolCall(
                            id="q1",
                            name=CONTROL_ASK,
                            arguments={
                                "question": "宠物叫什么名字？",
                                "slots": ["name"],
                            },
                        )
                    ],
                    stop_reason=StopReason.TOOL_CALLS,
                )
            ]
        )
        r1 = await _drain(
            run_stream(
                llm=llm,
                memory=mem,
                runner=runner,
                tools=tools,
                trigger=Message(role=Role.USER, content="加一只宠物"),
                system_before=system,
                system_after=system,
                wait_profile="turn_based",
                session_id=sid,
                store=store,
            )
        )
        assert r1.status == "waiting_user"
        assert r1.pending is not None and "名字" in r1.pending.prompt
        assert store.get(sid) and store.get(sid).pending is not None

        llm.extend(
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
                            arguments={"summary": "已登记宠物小花。"},
                        )
                    ],
                    stop_reason=StopReason.TOOL_CALLS,
                ),
            ]
        )
        r2 = await _drain(
            run_stream(
                llm=llm,
                memory=mem,
                runner=runner,
                tools=tools,
                trigger=Message(role=Role.USER, content="小花"),
                system_before=system,
                system_after=system,
                wait_profile="turn_based",
                session_id=sid,
                store=store,
                # pending 从 store 自动带上
            )
        )
        assert r2.status == "completed" and "小花" in r2.content
        assert store.get(sid).pending is None
        print("ok: turn_based 两轮 ask→act→finish")
    finally:
        Path(path).unlink(missing_ok=True)


async def test_interactive_resume() -> None:
    _, runner, tools = _kit()
    store = InMemorySessionStore()
    sid = "ix-1"
    system = "step3 interactive"
    mem, path = _tmp_memory("ix")
    try:
        llm = ScriptedLLM(
            [
                LLMOutput(
                    content="",
                    tool_calls=[
                        ToolCall(
                            id="q1",
                            name=CONTROL_ASK,
                            arguments={"question": "请确认宠物名？"},
                        )
                    ],
                    stop_reason=StopReason.TOOL_CALLS,
                )
            ]
        )
        awaiting: AwaitingUserEvent | None = None
        paused: RunResult | None = None
        async for item in run_stream(
            llm=llm,
            memory=mem,
            runner=runner,
            tools=tools,
            trigger=Message(role=Role.USER, content="加宠物"),
            system_before=system,
            system_after=system,
            wait_profile="interactive",
            session_id=sid,
            store=store,
        ):
            if isinstance(item, AwaitingUserEvent):
                awaiting = item
            if isinstance(item, RunResult):
                paused = item

        assert awaiting is not None and paused is not None
        assert paused.status == "awaiting_user"
        assert paused.await_token == awaiting.await_token
        assert store.get(sid).status == "awaiting_user"

        # 挂起中禁止 begin
        blocked = await _drain(
            run_stream(
                llm=llm,
                memory=mem,
                runner=runner,
                tools=tools,
                trigger=Message(role=Role.USER, content="插嘴"),
                system_before=system,
                system_after=system,
                wait_profile="interactive",
                session_id=sid,
                store=store,
            )
        )
        assert not blocked.ok and "awaiting_user" in blocked.error
        print("ok: interactive 挂起中拒绝 begin")

        llm.extend(
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
                            arguments={"summary": "已登记小花。"},
                        )
                    ],
                    stop_reason=StopReason.TOOL_CALLS,
                ),
            ]
        )
        done = await _drain(
            resume_stream(
                llm=llm,
                memory=mem,
                runner=runner,
                tools=tools,
                session_id=sid,
                store=store,
                user_reply="小花",
                run_id=awaiting.run_id,
                await_token=awaiting.await_token,
            )
        )
        assert done.status == "completed" and "小花" in done.content
        assert store.get(sid).status == "idle"
        assert store.get(sid).awaiting is None
        print("ok: interactive resume → act→finish")
    finally:
        Path(path).unlink(missing_ok=True)


async def test_no_wait_ask() -> None:
    _, runner, tools = _kit()
    system = "step3 no_wait"
    mem, path = _tmp_memory("nw")
    try:
        llm = ScriptedLLM(
            [
                LLMOutput(
                    content="",
                    tool_calls=[
                        ToolCall(
                            id="q1",
                            name=CONTROL_ASK,
                            arguments={"question": "还缺名字"},
                        )
                    ],
                    stop_reason=StopReason.TOOL_CALLS,
                )
            ]
        )
        result = await _drain(
            run_stream(
                llm=llm,
                memory=mem,
                runner=runner,
                tools=tools,
                trigger=Message(role=Role.USER, content="事件触发加宠"),
                system_before=system,
                system_after=system,
                wait_profile="no_wait",
            )
        )
        assert result.status == "failed" and not result.ok
        assert "no_wait" in result.content or "不允许等待" in result.content
        assert result.pending is None
        print("ok: no_wait 误 ask → failed（不挂死）")
    finally:
        Path(path).unlink(missing_ok=True)


async def test_pending_prompt_unit() -> None:
    p = PendingState(kind="ask", prompt="叫什么？", slots=["name"], intent="加宠")
    block = p.summary_for_prompt()
    assert "Pending" in block and "name" in block
    print("ok: pending summary")


def main() -> None:
    asyncio.run(test_pending_prompt_unit())
    asyncio.run(test_turn_based_two_rounds())
    asyncio.run(test_interactive_resume())
    asyncio.run(test_no_wait_ask())
    print("\nstep3: 全部通过")


if __name__ == "__main__":
    main()
