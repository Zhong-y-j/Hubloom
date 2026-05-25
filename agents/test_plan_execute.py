"""PlanExecute 冒烟：Plan 流式生成 → Execute 按步流式分发。

运行：
    PYTHONPATH=. uv run agents/test_plan_execute.py
"""

from __future__ import annotations

import asyncio
import json
import sys
import time
from typing import Any

from agents.events import (
    AgentEvent,
    ErrorEvent,
    ExecutionResultEvent,
    PlanCreatedEvent,
    PlanReadyEvent,
    PlanTextDeltaEvent,
    RunStatsEvent,
    StepCompleteEvent,
    StepErrorEvent,
    StepOutputDeltaEvent,
    StepStartEvent,
)
from agents.intent import StructuredIntent
from agents.plan_execute import (
    InMemoryAgentRegistry,
    LLMPlanGenerator,
    PlanExecuteAgent,
)
from agents.plan_models import ExecutionPlan, ExecutionResult, StepStatus
from agents.specialists import RegistryStepDelegate
from core import create_llm


def _build_registry() -> InMemoryAgentRegistry:
    reg = InMemoryAgentRegistry()
    reg.register(
        {
            "agent_id": "prog-001",
            "agent_type": "programming",
            "capabilities": ["programming"],
            "description": "编程与技术规格 Agent",
        }
    )
    reg.register(
        {
            "agent_id": "legal-001",
            "agent_type": "legal",
            "capabilities": ["legal"],
            "description": "法律条款 Agent",
        }
    )
    return reg


def _sample_intent() -> StructuredIntent:
    return StructuredIntent(
        is_clear=True,
        intent="contract_drafting",
        summary="撰写软件开发合同，含技术规格与法律条款",
        slots={
            "contract_type": "软件开发合同",
            "must_clauses": ["源代码归属", "付款节点"],
            "budget": "50000",
        },
        missing=[],
        user_reply="好的，我将为您规划并生成合同草案。",
    )


def _print_section(title: str) -> None:
    print(f"\n{'═' * 56}")
    print(f"▣ {title}")
    print(f"{'═' * 56}")


def _print_intent(intent: StructuredIntent) -> None:
    _print_section("输入 · StructuredIntent")
    print(json.dumps(intent.to_dict(), ensure_ascii=False, indent=2))
    print(f"\nshould_invoke_plan: {intent.should_invoke_plan()}")


def _print_plan_structured(plan: ExecutionPlan, *, elapsed_ms: int) -> None:
    _print_section("Plan 解析结果 · ExecutionPlan")
    print(f"task_type: {plan.task_type}")
    print(f"rationale: {plan.rationale or '（无）'}")
    print(f"步骤数: {len(plan.steps)}  |  耗时: {elapsed_ms} ms\n")

    for step in sorted(plan.steps, key=lambda s: s.step_id):
        deps = (
            ", ".join(str(d) for d in step.dependencies) if step.dependencies else "无"
        )
        print(f"── 步骤 {step.step_id} · {step.agent_type} ──")
        print(f"  依赖: {deps}")
        print(f"  任务: {step.task_description}")
        print(f"  预期产出: {step.expected_output or '（未填）'}\n")


class PlanExecuteStreamPrinter:
    """Plan / Execute 流式终端输出。"""

    def __init__(self) -> None:
        self._execute_order = 0
        self._plan_streaming = False
        self._step_streaming = False
        self._current_step_id: int | None = None

    def _end_line_if_streaming(self) -> None:
        if self._plan_streaming or self._step_streaming:
            print()
            self._plan_streaming = False
            self._step_streaming = False

    # ── Plan 阶段 ─────────────────────────────────────────

    def begin_plan(self) -> None:
        _print_section("Plan 生成 · LLMPlanGenerator（流式）")
        print("模型原始输出（```plan``` JSON）：\n")

    def handle_plan_event(self, ev: AgentEvent) -> ExecutionPlan | None:
        if isinstance(ev, PlanTextDeltaEvent):
            sys.stdout.write(ev.delta)
            sys.stdout.flush()
            self._plan_streaming = True
            return None
        if isinstance(ev, PlanReadyEvent):
            self._end_line_if_streaming()
            return ev.plan
        if isinstance(ev, ErrorEvent):
            self._end_line_if_streaming()
            print(f"\n✗ Plan 阶段: {ev.error}", file=sys.stderr)
        return None

    # ── Execute 阶段 ───────────────────────────────────────

    def handle_execute_event(self, ev: AgentEvent) -> None:
        if isinstance(ev, PlanTextDeltaEvent):
            return

        if isinstance(ev, PlanCreatedEvent):
            self._end_line_if_streaming()
            _print_section("Execute 阶段 · 按 plan 串行分发")
            print(f"将执行 {len(ev.steps)} 个步骤（有依赖则等待前置完成）\n")
            return

        if isinstance(ev, StepStartEvent):
            self._end_line_if_streaming()
            self._execute_order += 1
            self._current_step_id = ev.step_id
            print(f"{'─' * 56}")
            print(
                f"▶ [{self._execute_order}] step_id={ev.step_id} · "
                f"{ev.agent_type or '?'} · agent={ev.agent_id or '?'}"
            )
            print(f"{'─' * 56}")
            print(f"  动作: delegate_stream → 专业 Agent")
            print(f"  任务: {ev.description}")
            print(f"\n  ▷ Agent 输出（流式）：\n")
            return

        if isinstance(ev, StepOutputDeltaEvent):
            sys.stdout.write(ev.delta)
            sys.stdout.flush()
            self._step_streaming = True
            return

        if isinstance(ev, StepCompleteEvent):
            self._end_line_if_streaming()
            chars = len(ev.summary or "")
            print(f"  ✓ step_id={ev.step_id} 完成（约 {chars} 字预览入 trace）\n")
            return

        if isinstance(ev, StepErrorEvent):
            self._end_line_if_streaming()
            print(
                f"  ✗ step_id={ev.step_id} 失败: {ev.error}",
                file=sys.stderr,
            )
            print()
            return

        if isinstance(ev, RunStatsEvent):
            _print_section("Execute 阶段 · 统计")
            print(f"  计划步骤数: {ev.steps}")
            print(f"  实际分发次数: {ev.tool_calls}")
            print(f"  失败次数: {ev.tool_errors}")
            print(f"  Execute 耗时: {ev.elapsed_ms} ms")
            return

        if isinstance(ev, ExecutionResultEvent):
            self._print_result_brief(ev.result)
            return

        if isinstance(ev, ErrorEvent):
            self._end_line_if_streaming()
            print(f"\n✗ {ev.error}", file=sys.stderr)
            return

    def _print_result_brief(self, result: Any) -> None:
        if not isinstance(result, ExecutionResult):
            return
        _print_section("Execute 阶段 · 汇总（简要）")
        print(f"  partial_success: {result.partial_success}")
        for row in result.trace:
            out_len = len(row.output or "")
            print(
                f"  [{row.step_id}] {row.agent_type} | {row.status.value} | "
                f"agent={row.agent_id or '-'} | 产出 {out_len} 字"
            )
        print("\n  deliverable 前 300 字:")
        print(f"  {(result.deliverable or '')[:300]}…")


async def _run_plan_stream(
    intent: StructuredIntent,
    registry: InMemoryAgentRegistry,
    llm: Any,
    printer: PlanExecuteStreamPrinter,
) -> ExecutionPlan:
    generator = LLMPlanGenerator(llm, registry=registry)
    printer.begin_plan()
    t0 = time.monotonic()
    plan: ExecutionPlan | None = None
    async for ev in generator.create_plan_stream(intent):
        got = printer.handle_plan_event(ev)
        if got is not None:
            plan = got
    if plan is None:
        raise RuntimeError("Plan 阶段未收到 PlanReadyEvent")
    _print_plan_structured(plan, elapsed_ms=int((time.monotonic() - t0) * 1000))
    return plan


async def _run_execute_stream(
    intent: StructuredIntent,
    plan: ExecutionPlan,
    registry: InMemoryAgentRegistry,
    llm: Any,
    printer: PlanExecuteStreamPrinter,
) -> None:
    _print_section("Execute 分发 · RegistryStepDelegate")
    print("programming → LLMSpecialistAgent(prog-001)")
    print("legal       → LLMSpecialistAgent(legal-001)\n")

    agent = PlanExecuteAgent(
        llm,
        plan_generator=LLMPlanGenerator(llm, registry=registry),
        registry=registry,
        step_delegate=RegistryStepDelegate(llm),
    )
    async for ev in agent.execute_stream(
        intent,
        plan=plan,
        skip_plan_generation=True,
    ):
        printer.handle_execute_event(ev)


async def main() -> None:
    intent = _sample_intent()
    registry = _build_registry()
    llm = create_llm()
    printer = PlanExecuteStreamPrinter()

    _print_intent(intent)

    _print_section("可用专业 Agent（Registry）")
    print(json.dumps(await registry.list_agents(), ensure_ascii=False, indent=2))

    if not intent.should_invoke_plan():
        print("\n✗ 当前 intent 不应进入 PlanExecute", file=sys.stderr)
        sys.exit(1)

    try:
        plan = await _run_plan_stream(intent, registry, llm, printer)
    except Exception as exc:
        print(f"\n✗ 计划生成失败: {exc}", file=sys.stderr)
        sys.exit(1)

    await _run_execute_stream(intent, plan, registry, llm, printer)
    print()


if __name__ == "__main__":
    asyncio.run(main())
