"""Agent 整流程集成测试（不经 Runtime / 不拆 step）。

覆盖一条完整办事链：
Ask（turn_based pending）→ Gate 打回提前 finish → 须确认 → Act 入 Journal → Finish(cites)

另含：interactive resume、no_wait 降级。

用法::

    PYTHONPATH=src .venv/bin/python tests/test_agent_v2_flow.py
"""

from __future__ import annotations

import asyncio
import tempfile
from collections.abc import AsyncIterator, Sequence
from pathlib import Path
from typing import Any

from agent.actions import CONTROL_ASK, CONTROL_CONFIRM, CONTROL_FINISH
from agent.events import (
    AwaitingUserEvent,
    PolicyRejectEvent,
    RunCompleteEvent,
    StepEvent,
    ToolResultEvent,
)
from agent.policy import Playbook, RequireStep
from agent.run import RunResult, resume_stream, run_stream
from redis_test_utils import make_fake_session_backends
from core.models import LLMOutput, Message, Role, StopReason, ToolCall
from core.provider import LLMProvider, LLMStreamEvent, StreamEndEvent
from memory import create_memory_manager
from tools.base import BaseTool
from tools.registry import ToolRegistry
from tools.runner import ToolRunner


class ScriptedLLM(LLMProvider):
    """按序吐出预设 Decide 输出；可用 extend 追加后续轮。"""

    def __init__(self, outputs: Sequence[LLMOutput] | None = None) -> None:
        self._outputs = list(outputs or [])
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
        raise RuntimeError("ScriptedLLM: no output")

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


class EchoPetTool(BaseTool):
    name = "echo_pet"
    description = "登记宠物"
    parameters = {
        "type": "object",
        "properties": {"name": {"type": "string"}},
        "required": ["name"],
    }

    async def execute(self, **kwargs: Any) -> str:
        return f"registered:{kwargs.get('name', '')}"


def _tc(oid: str, name: str, arguments: dict[str, Any] | None = None) -> ToolCall:
    return ToolCall(id=oid, name=name, arguments=arguments or {})


def _out(*calls: ToolCall) -> LLMOutput:
    return LLMOutput(
        content="",
        tool_calls=list(calls),
        stop_reason=StopReason.TOOL_CALLS,
    )


def _tmp_memory(ns: str):
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


def _kit():
    registry = ToolRegistry.from_tools([EchoPetTool()])
    return ToolRunner(registry), registry.list_definitions()


def _playbook() -> Playbook:
    """加宠规程：须确认后登记；登记完成才可 finish。"""
    return Playbook(
        require_steps=(RequireStep(id="register_pet", tools=("echo_pet",)),),
        confirm_tools=frozenset({"echo_pet"}),
        sources=("flow-test",),
    )


async def _collect(agen) -> tuple[RunResult, list[Any]]:
    items: list[Any] = []
    result: RunResult | None = None
    async for item in agen:
        items.append(item)
        if isinstance(item, RunResult):
            result = item
    if result is None:
        raise AssertionError("未收到 RunResult")
    return result, items


# ---------------------------------------------------------------------------
# 主流程：企微式 turn_based 办事链
# ---------------------------------------------------------------------------


async def test_full_turn_based_pet_flow() -> None:
    runner, tools = _kit()
    book = _playbook()
    store, _lock = make_fake_session_backends()
    sid = "flow-pet"
    system = "集成测试：按 Playbook 办事。"
    mem, path = _tmp_memory("flow-tb")
    llm = ScriptedLLM()

    try:
        # --- Round 1：缺参 → ask ---
        llm.extend(
            [
                _out(
                    _tc(
                        "q1",
                        CONTROL_ASK,
                        {"question": "宠物叫什么名字？", "slots": ["name"]},
                    )
                )
            ]
        )
        r1, items1 = await _collect(
            run_stream(
                llm=llm,
                memory=mem,
                runner=runner,
                tools=tools,
                trigger=Message(role=Role.USER, content="帮我加一只宠物"),
                system_before=system,
                system_after=system,
                wait_profile="turn_based",
                session_id=sid,
                store=store,
                playbook=book,
                max_rounds=8,
            )
        )
        assert r1.status == "waiting_user"
        assert r1.pending is not None and "名字" in r1.pending.prompt
        assert any(isinstance(x, StepEvent) and x.action == "ask" for x in items1)
        assert any(isinstance(x, RunCompleteEvent) for x in items1)
        assert store.get(sid) and store.get(sid).pending is not None
        print("  · round1 ask → waiting_user + pending")

        # --- Round 2：回名字；先违规 finish / 未确认 act，再 confirm ---
        llm.extend(
            [
                _out(
                    _tc(
                        "f0",
                        CONTROL_FINISH,
                        {"summary": "还没登记就说完成了"},
                    )
                ),
                _out(_tc("a0", "echo_pet", {"name": "小花"})),
                _out(
                    _tc(
                        "c1",
                        CONTROL_CONFIRM,
                        {"prompt": "确认登记宠物小花？"},
                    )
                ),
            ]
        )
        r2, items2 = await _collect(
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
                playbook=book,
                max_rounds=8,
            )
        )
        rejects = [x for x in items2 if isinstance(x, PolicyRejectEvent)]
        codes = {x.code for x in rejects}
        assert "require_steps" in codes
        assert "need_confirm" in codes
        assert r2.status == "waiting_user"
        assert r2.pending is not None and r2.pending.kind == "await_confirm"
        print("  · round2 Gate 打回 finish/act → await_confirm")

        # --- Round 3：用户确认 → act → finish(cites) ---
        llm.extend(
            [
                _out(_tc("a1", "echo_pet", {"name": "小花"})),
                _out(
                    _tc(
                        "f1",
                        CONTROL_FINISH,
                        {
                            "summary": "已登记宠物小花。",
                            "cites": [],  # 运行时再填真实 journal id
                        },
                    )
                ),
            ]
        )
        # 动态 cites：先跑到 tool result 再改脚本较难；改为断言 evidence_ids 非空 + finish 成功
        # 把 finish 的 cites 在第二段脚本里用占位，验收看 journal / complete
        r3, items3 = await _collect(
            run_stream(
                llm=llm,
                memory=mem,
                runner=runner,
                tools=tools,
                trigger=Message(role=Role.USER, content="确认"),
                system_before=system,
                system_after=system,
                wait_profile="turn_based",
                session_id=sid,
                store=store,
                playbook=book,
                max_rounds=8,
            )
        )
        tool_evs = [x for x in items3 if isinstance(x, ToolResultEvent)]
        assert tool_evs and tool_evs[0].journal_id
        assert "registered:小花" in tool_evs[0].result
        assert any(isinstance(x, StepEvent) and x.action == "act" for x in items3)
        assert any(isinstance(x, StepEvent) and x.action == "finish" for x in items3)
        complete = next(x for x in items3 if isinstance(x, RunCompleteEvent))
        assert complete.status == "completed"
        assert complete.journal_run_id
        assert tool_evs[0].journal_id in complete.evidence_ids
        assert r3.ok and r3.status == "completed"
        assert "小花" in r3.content
        assert r3.journal_run_id == complete.journal_run_id
        assert store.get(sid).pending is None
        print("  · round3 confirm → act(Journal) → finish → completed")
        print("ok: 整流程 turn_based 加宠（Ask→Gate→Confirm→Act→Finish）")
    finally:
        Path(path).unlink(missing_ok=True)


# ---------------------------------------------------------------------------
# 辅：interactive 同 Run 挂起恢复
# ---------------------------------------------------------------------------


async def test_full_interactive_resume_flow() -> None:
    runner, tools = _kit()
    store, _lock = make_fake_session_backends()
    sid = "flow-ix"
    system = "集成测试 interactive"
    mem, path = _tmp_memory("flow-ix")
    # interactive 不强制 playbook，突出挂起/resume
    llm = ScriptedLLM(
        [
            _out(
                _tc("q1", CONTROL_ASK, {"question": "叫什么名字？"})
            )
        ]
    )
    try:
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
            max_rounds=6,
        ):
            if isinstance(item, AwaitingUserEvent):
                awaiting = item
            if isinstance(item, RunResult):
                paused = item

        assert awaiting and paused and paused.status == "awaiting_user"

        llm.extend(
            [
                _out(_tc("a1", "echo_pet", {"name": "豆豆"})),
                _out(
                    _tc(
                        "f1",
                        CONTROL_FINISH,
                        {"summary": "已登记豆豆。"},
                    )
                ),
            ]
        )
        done, items = await _collect(
            resume_stream(
                llm=llm,
                memory=mem,
                runner=runner,
                tools=tools,
                session_id=sid,
                store=store,
                user_reply="豆豆",
                run_id=awaiting.run_id,
                await_token=awaiting.await_token,
            )
        )
        assert done.status == "completed" and "豆豆" in done.content
        assert any(isinstance(x, RunCompleteEvent) for x in items)
        assert store.get(sid).status == "idle"
        print("ok: 整流程 interactive ask→resume→act→finish")
    finally:
        Path(path).unlink(missing_ok=True)


# ---------------------------------------------------------------------------
# 辅：事件入口 no_wait
# ---------------------------------------------------------------------------


async def test_full_no_wait_does_not_hang() -> None:
    runner, tools = _kit()
    mem, path = _tmp_memory("flow-nw")
    try:
        llm = ScriptedLLM(
            [_out(_tc("q1", CONTROL_ASK, {"question": "还缺参数"}))]
        )
        result, _ = await _collect(
            run_stream(
                llm=llm,
                memory=mem,
                runner=runner,
                tools=tools,
                trigger=Message(role=Role.USER, content="事件：加宠"),
                system_before="s",
                system_after="s",
                wait_profile="no_wait",
            )
        )
        assert result.status == "failed" and not result.ok
        assert result.pending is None
        print("ok: 整流程 no_wait 误 ask → failed")
    finally:
        Path(path).unlink(missing_ok=True)


def main() -> None:
    print("Agent 整流程集成（无 Runtime）\n")
    asyncio.run(test_full_turn_based_pet_flow())
    asyncio.run(test_full_interactive_resume_flow())
    asyncio.run(test_full_no_wait_does_not_hang())
    print("\nflow: 全部通过")


if __name__ == "__main__":
    main()
