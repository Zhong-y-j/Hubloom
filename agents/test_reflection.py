"""Reflection 冒烟：输入 ExecutionResult，输出 ReflectionVerdict。

运行：
    PYTHONPATH=. uv run agents/test_reflection.py
    REFLECTION_FIXTURE=fail PYTHONPATH=. uv run agents/test_reflection.py
"""

from __future__ import annotations

import asyncio
import json
import os
import sys

from agents.events import (
    AgentEvent,
    ErrorEvent,
    ReflectionCompleteEvent,
    ReflectionStartEvent,
    ReflectionTextDeltaEvent,
)
from agents.intent import StructuredIntent
from agents.plan_models import (
    ExecutionPlan,
    ExecutionResult,
    ExecutionStep,
    ExecutionStepTrace,
    StepStatus,
)
from agents.reflection import ReflectionAgent
from agents.reflection_models import ReflectionVerdict
from core import create_llm


def _print_section(title: str) -> None:
    print(f"\n{'═' * 56}")
    print(f"▣ {title}")
    print(f"{'═' * 56}")


def _base_intent() -> StructuredIntent:
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


def _fixture_pass() -> ExecutionResult:
    """预期：LLM 审查倾向 passed=true。"""
    tech = """**技术附件**
开发范围：Web 应用；预算上限人民币 50,000 元。
交付：源码仓库权限 + 部署文档。源代码验收后归甲方。"""
    legal = """**软件开发合同（草案）**
总价款人民币 50,000 元，分三期：20%/40%/40%。
知识产权：付清全款且验收后源代码归甲方。含付款节点与源代码归属条款。"""
    return ExecutionResult(
        deliverable=f"## 步骤 1\n{tech}\n\n## 步骤 2\n{legal}",
        trace=[
            ExecutionStepTrace(
                step_id=1,
                agent_type="programming",
                status=StepStatus.SUCCESS,
                output=tech,
                agent_id="prog-001",
            ),
            ExecutionStepTrace(
                step_id=2,
                agent_type="legal",
                status=StepStatus.SUCCESS,
                output=legal,
                agent_id="legal-001",
            ),
        ],
        partial_success=False,
        plan=ExecutionPlan(
            task_type="contract_drafting",
            rationale="先技术后法律",
            steps=[
                ExecutionStep(
                    step_id=1,
                    agent_type="programming",
                    task_description="技术规格",
                    dependencies=[],
                ),
                ExecutionStep(
                    step_id=2,
                    agent_type="legal",
                    task_description="法律条款",
                    dependencies=[1],
                ),
            ],
        ),
        source_intent=_base_intent(),
    )


def _fixture_fail() -> ExecutionResult:
    """预期：LLM 审查倾向 passed=false（预算与正文不一致）。"""
    result = _fixture_pass()
    bad_legal = result.trace[1].output.replace("50,000", "80,000")
    result.trace[1].output = bad_legal
    result.deliverable = f"## 步骤 1\n{result.trace[0].output}\n\n## 步骤 2\n{bad_legal}"
    return result


def _fixture_execution_failed() -> ExecutionResult:
    """L0 规则：不调用 LLM，直接不通过。"""
    return ExecutionResult(
        deliverable="",
        trace=[
            ExecutionStepTrace(
                step_id=1,
                agent_type="programming",
                status=StepStatus.FAILED,
                error="模拟步骤失败",
            ),
        ],
        partial_success=True,
        source_intent=_base_intent(),
    )


def _print_input_summary(result: ExecutionResult) -> None:
    _print_section("输入 · ExecutionResult（PlanExecute 输出）")
    print(f"  deliverable 长度: {len(result.deliverable or '')} 字")
    print(f"  trace 步数: {len(result.trace)}")
    print(f"  partial_success: {result.partial_success}")
    if result.source_intent:
        print(f"  intent: {result.source_intent.intent}")
        print(f"  slots.budget: {result.source_intent.slots.get('budget')}")


def _print_verdict(verdict: ReflectionVerdict) -> None:
    """Reflection 的核心输出：ReflectionVerdict。"""
    _print_section("输出 · ReflectionVerdict（Reflection 结论，供 Hub 使用）")
    print(json.dumps(verdict.to_dict(), ensure_ascii=False, indent=2))
    print()
    print("── 字段说明 ──")
    print(f"  passed          = {verdict.passed}")
    print("    → True：建议将当前 deliverable 交付给用户")
    print("    → False：Hub 应触发「优化」（重跑 PlanExecute 某步或展示 issues）")
    print(f"  summary         = {verdict.summary!r}")
    print(f"  issues          = {len(verdict.issues)} 条 "
          f"(error={verdict.error_count}, warning={verdict.warning_count})")
    for i, issue in enumerate(verdict.issues, 1):
        print(
            f"    [{i}] {issue.severity} · {issue.category} · "
            f"steps={issue.related_step_ids} · {issue.message[:80]}"
        )
    print(f"  recommendation  = {verdict.recommendation!r}")
    print("    → Hub 可据此决定重跑哪些 step_id")
    if verdict.review_report:
        print(f"  review_report   = {len(verdict.review_report)} 字（LLM 全文，见上方流式）")


class ReflectionStreamPrinter:
    def __init__(self) -> None:
        self._streaming = False

    def handle(self, ev: AgentEvent) -> ReflectionVerdict | None:
        if isinstance(ev, ReflectionStartEvent):
            _print_section("Reflection 阶段 · 审查开始（流式）")
            print(
                f"  审查步数 trace={ev.step_count}  "
                f"partial_success={ev.partial_success}"
            )
            print("\n  ▷ 审查说明（流式）：\n")
            return None

        if isinstance(ev, ReflectionTextDeltaEvent):
            sys.stdout.write(ev.delta)
            sys.stdout.flush()
            self._streaming = True
            return None

        if isinstance(ev, ReflectionCompleteEvent):
            if self._streaming:
                print()
                self._streaming = False
            print(f"\n  审查耗时: {ev.elapsed_ms} ms")
            _print_verdict(ev.verdict)
            return ev.verdict

        if isinstance(ev, ErrorEvent):
            print(f"\n✗ {ev.error}", file=sys.stderr)
            return None

        return None


async def main() -> None:
    fixture = os.getenv("REFLECTION_FIXTURE", "pass").lower()
    if fixture == "fail":
        result = _fixture_fail()
        label = "fail（预算故意不一致，期望 passed=false）"
    elif fixture == "exec_fail":
        result = _fixture_execution_failed()
        label = "exec_fail（L0 规则，不调 LLM）"
    else:
        result = _fixture_pass()
        label = "pass（一致样例，期望 passed=true）"

    _print_section(f"Reflection 冒烟 · fixture={label}")
    _print_input_summary(result)

    agent = ReflectionAgent(create_llm())
    printer = ReflectionStreamPrinter()
    verdict: ReflectionVerdict | None = None
    async for ev in agent.review_stream(result):
        got = printer.handle(ev)
        if got is not None:
            verdict = got

    if verdict is None:
        verdict = agent.get_last_verdict()

    _print_section("Hub 将如何使用此输出（示意）")
    if verdict and verdict.passed:
        print("  if verdict.passed → 向用户展示 PlanExecute.deliverable")
    else:
        print("  if not verdict.passed → 读取 verdict.issues / recommendation")
        print("  → 由 Hub 决定是否重跑 PlanExecute（优化），而非 Reflection 改稿")
    print()


if __name__ == "__main__":
    asyncio.run(main())
