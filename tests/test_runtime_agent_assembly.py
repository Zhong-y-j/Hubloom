"""经 HubloomRuntime 跑一条完整办事任务（不经示例站 / 不需真 LLM Key）。

任务故事（turn_based，模拟企微多轮）：
  用户「帮我加一只宠物」
    → Agent 追问名字（pending 进 SessionStore）
    → 用户回「小花」；模型先违规 finish / 未确认 act，被 Playbook Gate 打回，再请求确认
    → 用户「确认」→ 调用登记工具（Journal）→ finish 收工

另测：interactive 同任务挂起 resume；配置 default_wait_profile。

用法::

    PYTHONPATH=src .venv/bin/python tests/test_runtime_agent_assembly.py
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
    FinalAnswerEvent,
    PolicyRejectEvent,
    RunCompleteEvent,
    StepEvent,
    ToolCallEvent,
    ToolResultEvent,
)
from agent.policy import Playbook, compile_playbook_from_skills
from agent.run import RunResult
from redis_test_utils import make_fake_session_backends
from config import HubloomConfig
from core.models import LLMOutput, Message, Role, StopReason, ToolCall
from core.provider import LLMProvider, LLMStreamEvent, StreamEndEvent
from runtime import HubloomRuntime
from skill import load_skills
from tools.base import BaseTool


class ScriptedLLM(LLMProvider):
    """按序吐出预设 Decide；任务中途可用 extend 追加。"""

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


class EchoPetTool(BaseTool):
    """模拟业务登记接口（Runtime 里当 MCP 工具挂上）。"""

    name = "echo_pet"
    description = "登记宠物"
    parameters = {
        "type": "object",
        "properties": {"name": {"type": "string"}},
        "required": ["name"],
    }

    async def execute(self, **kwargs: Any) -> str:
        return f"registered:{kwargs.get('name', '')}"


def _tc(oid: str, name: str, args: dict[str, Any] | None = None) -> ToolCall:
    return ToolCall(id=oid, name=name, arguments=args or {})


def _out(*calls: ToolCall) -> LLMOutput:
    return LLMOutput(
        content="",
        tool_calls=list(calls),
        stop_reason=StopReason.TOOL_CALLS,
    )


def _write_pet_skill(skills_root: Path) -> Path:
    """厂规：须确认 → 登记成功 → 才允许 finish。"""
    folder = skills_root / "pet-register"
    folder.mkdir(parents=True)
    (folder / "SKILL.md").write_text(
        """---
name: pet-register
description: 加宠须确认并登记后才能 finish
playbook:
  require_steps:
    - id: register_pet
      tools: [echo_pet]
  confirm_tools: [echo_pet]
---

# pet-register
完整加宠任务规程。
""",
        encoding="utf-8",
    )
    return skills_root


def _build_runtime(
    *,
    llm: ScriptedLLM,
    skills_dir: Path,
    memory_db: Path,
    wait_profile: str = "turn_based",
    playbook: Playbook | None = None,
) -> HubloomRuntime:
    cfg = HubloomConfig(
        openai_api_key="test-not-used",
        enable_mcp=False,
        skills_dir=str(skills_dir),
        memory_db_path=str(memory_db),
        default_wait_profile=wait_profile,
        agent_log=False,
        cortex_log=False,
        memory_log=False,
    )
    if playbook is None:
        playbook = compile_playbook_from_skills(load_skills(skills_dir))
    store, lock = make_fake_session_backends()
    return HubloomRuntime(
        cfg=cfg,
        llm=llm,
        system_before="你是办事 Agent：按 Playbook 完成加宠任务。",
        system_after="已有工具结果，继续合规动作直至 finish。",
        mcp_setup=None,
        _mcp_tools=[EchoPetTool()],
        playbook=playbook,
        session_store=store,
        session_lock=lock,
        default_wait_profile=wait_profile,
        max_rounds=8,
    )


async def _run_turn(
    rt: HubloomRuntime,
    text: str,
    *,
    session_id: str,
    wait_profile: str | None = None,
) -> tuple[RunResult, list[Any]]:
    items: list[Any] = []
    result: RunResult | None = None
    kwargs: dict[str, Any] = {"session_id": session_id}
    if wait_profile is not None:
        kwargs["wait_profile"] = wait_profile
    async for item in rt.run_stream(
        Message(role=Role.USER, content=text),
        **kwargs,
    ):
        items.append(item)
        if isinstance(item, RunResult):
            result = item
    if result is None:
        raise AssertionError(f"回合无 RunResult: {text!r}")
    return result, items


# ---------------------------------------------------------------------------
# 主验收：一条完整加宠任务（经 Runtime）
# ---------------------------------------------------------------------------


async def test_complete_task_add_pet_via_runtime() -> None:
    """完整任务：缺参追问 → 规程拦截 → 确认 → 登记 → 收工。"""
    tmp = Path(tempfile.mkdtemp())
    skills = _write_pet_skill(tmp / "skills")
    llm = ScriptedLLM()
    rt = _build_runtime(
        llm=llm,
        skills_dir=skills,
        memory_db=tmp / "task.db",
        wait_profile="turn_based",
    )
    sid = "task-add-pet"

    print("任务：经 Runtime 加一只宠物（turn_based）\n")

    try:
        # 装配自检：Skill → Playbook 已进 Runtime
        assert not rt.playbook.is_empty()
        assert "echo_pet" in rt.playbook.confirm_tools
        assert any(s.id == "register_pet" for s in rt.playbook.require_steps)
        print("① 装配就绪：Playbook(confirm+require) + SessionStore + echo_pet")

        # ---------- 回合 1：用户开口，缺参 ----------
        llm.extend(
            [
                _out(
                    _tc(
                        "q1",
                        CONTROL_ASK,
                        {
                            "question": "请问宠物叫什么名字？",
                            "slots": ["name"],
                        },
                    )
                )
            ]
        )
        r1, items1 = await _run_turn(
            rt, "帮我加一只宠物", session_id=sid, wait_profile="turn_based"
        )

        assert r1.status == "waiting_user"
        assert "名字" in r1.content
        assert r1.pending is not None
        assert r1.pending.slots == ["name"]
        assert any(isinstance(x, StepEvent) and x.action == "ask" for x in items1)
        assert any(isinstance(x, FinalAnswerEvent) for x in items1)
        assert any(isinstance(x, RunCompleteEvent) and x.status == "waiting_user" for x in items1)
        rec = rt.session_store.get(sid)
        assert rec is not None and rec.pending is not None
        print("② 用户「帮我加一只宠物」→ ask → waiting_user，pending 已落 Store")

        # ---------- 回合 2：给名字；故意违规再确认 ----------
        llm.extend(
            [
                # 未登记就 finish → Gate require_steps
                _out(
                    _tc(
                        "f0",
                        CONTROL_FINISH,
                        {"summary": "好的已经加好了（其实没有）"},
                    )
                ),
                # 未确认就登记 → Gate need_confirm
                _out(_tc("a0", "echo_pet", {"name": "小花"})),
                # 合规：先确认
                _out(
                    _tc(
                        "c1",
                        CONTROL_CONFIRM,
                        {"prompt": "确认将登记宠物「小花」吗？"},
                    )
                ),
            ]
        )
        r2, items2 = await _run_turn(rt, "小花", session_id=sid)

        reject_codes = {x.code for x in items2 if isinstance(x, PolicyRejectEvent)}
        assert "require_steps" in reject_codes
        assert "need_confirm" in reject_codes
        assert r2.status == "waiting_user"
        assert r2.pending is not None and r2.pending.kind == "await_confirm"
        assert "小花" in r2.content
        assert any(
            isinstance(x, StepEvent) and x.action == "await_confirm" for x in items2
        )
        print("③ 用户「小花」→ Gate 打回违规 finish/act → await_confirm")

        # ---------- 回合 3：确认后登记并收工 ----------
        llm.extend(
            [
                _out(_tc("a1", "echo_pet", {"name": "小花"})),
                _out(
                    _tc(
                        "f1",
                        CONTROL_FINISH,
                        {"summary": "已为您登记宠物小花，任务完成。"},
                    )
                ),
            ]
        )
        r3, items3 = await _run_turn(rt, "确认", session_id=sid)

        tool_calls = [x for x in items3 if isinstance(x, ToolCallEvent)]
        tool_results = [x for x in items3 if isinstance(x, ToolResultEvent)]
        assert any(x.tool_name == "echo_pet" for x in tool_calls)
        assert tool_results and "registered:小花" in tool_results[0].result
        assert tool_results[0].journal_id  # Evidence Journal 入账

        assert any(isinstance(x, StepEvent) and x.action == "act" for x in items3)
        assert any(isinstance(x, StepEvent) and x.action == "finish" for x in items3)

        complete = next(x for x in items3 if isinstance(x, RunCompleteEvent))
        assert complete.status == "completed"
        assert complete.ok
        assert tool_results[0].journal_id in complete.evidence_ids

        assert r3.ok and r3.status == "completed"
        assert "小花" in r3.content
        assert r3.journal_run_id == complete.journal_run_id
        assert r3.tool_calls >= 1
        assert rt.session_store.get(sid).pending is None

        print("④ 用户「确认」→ act(echo_pet+Journal) → finish → completed")
        print(
            f"   journal_run_id={r3.journal_run_id} "
            f"evidence={complete.evidence_ids}"
        )
        print("\nok: 完整任务办完（Runtime 装配链路）")
    finally:
        await rt.aclose()


# ---------------------------------------------------------------------------
# 同任务 interactive 变体（网页挂起）
# ---------------------------------------------------------------------------


async def test_complete_task_add_pet_interactive() -> None:
    """同一加宠任务：interactive 下 ask 挂起，resume 后登记收工。"""
    tmp = Path(tempfile.mkdtemp())
    skills = _write_pet_skill(tmp / "skills")
    llm = ScriptedLLM(
        [_out(_tc("q1", CONTROL_ASK, {"question": "宠物叫什么名字？"}))]
    )
    # 本变体用空 Playbook，突出 Runtime.resume_stream；规程已在主任务覆盖
    rt = _build_runtime(
        llm=llm,
        skills_dir=skills,
        memory_db=tmp / "task-ix.db",
        wait_profile="interactive",
        playbook=Playbook(),
    )
    sid = "task-add-pet-ix"

    print("\n任务变体：interactive 挂起加宠\n")
    try:
        awaiting: AwaitingUserEvent | None = None
        paused: RunResult | None = None
        async for item in rt.run_stream(
            Message(role=Role.USER, content="帮我加一只宠物"),
            session_id=sid,
        ):
            if isinstance(item, AwaitingUserEvent):
                awaiting = item
            if isinstance(item, RunResult):
                paused = item

        assert awaiting is not None
        assert paused is not None and paused.status == "awaiting_user"
        assert rt.session_store.get(sid).status == "awaiting_user"
        print("① ask → awaiting_user（同一 Run 挂起）")

        llm.extend(
            [
                _out(_tc("a1", "echo_pet", {"name": "豆豆"})),
                _out(
                    _tc(
                        "f1",
                        CONTROL_FINISH,
                        {"summary": "已登记宠物豆豆，任务完成。"},
                    )
                ),
            ]
        )
        items: list[Any] = []
        done: RunResult | None = None
        async for item in rt.resume_stream(
            session_id=sid,
            user_reply="豆豆",
            run_id=awaiting.run_id,
            await_token=awaiting.await_token,
        ):
            items.append(item)
            if isinstance(item, RunResult):
                done = item

        assert done is not None
        assert done.status == "completed" and "豆豆" in done.content
        assert any(isinstance(x, ToolResultEvent) for x in items)
        assert any(isinstance(x, RunCompleteEvent) for x in items)
        assert rt.session_store.get(sid).status == "idle"
        print("② resume「豆豆」→ act → finish → completed")
        print("\nok: interactive 完整任务办完")
    finally:
        await rt.aclose()


def test_config_wait_profile_parse() -> None:
    text = """
llm:
  api_key: k
  model: m
mcp:
  enable: false
agent:
  default_wait_profile: no_wait
skills_dir: skills
"""
    path = Path(tempfile.mkdtemp()) / "cfg.yaml"
    path.write_text(text, encoding="utf-8")
    cfg = HubloomConfig.from_file(path)
    assert cfg.default_wait_profile == "no_wait"
    print("ok: config agent.default_wait_profile")


def main() -> None:
    print("=" * 56)
    print(" Runtime 完整任务流程测试（无示例站）")
    print("=" * 56 + "\n")
    test_config_wait_profile_parse()
    print()
    asyncio.run(test_complete_task_add_pet_via_runtime())
    asyncio.run(test_complete_task_add_pet_interactive())
    print("\n" + "=" * 56)
    print(" 全部通过")
    print("=" * 56)


if __name__ == "__main__":
    main()
