"""Hub 终端交互：事件打印与单轮 / REPL 运行。"""

from __future__ import annotations

import json
import re
import sys

from agents.core.events import (
    AgentEvent,
    ErrorEvent,
    ExecutionResultEvent,
    FinalAnswerEvent,
    HubPhaseEvent,
    HubTurnCompleteEvent,
    IntentOutcomeEvent,
    MemoryConsolidatedEvent,
    PlanCreatedEvent,
    PlanReadyEvent,
    ReflectionCompleteEvent,
    ReflectionStartEvent,
    ReflectionTextDeltaEvent,
    RunStatsEvent,
    StepCompleteEvent,
    StepErrorEvent,
    StepOutputDeltaEvent,
    StepStartEvent,
    TextDeltaEvent,
    ToolCallEvent,
    ToolResultEvent,
)
from agents.hub import CortexHub
from agents.plan.models import ExecutionPlan


def print_section(title: str) -> None:
    print(f"\n{'═' * 56}")
    print(f"▣ {title}")
    print(f"{'═' * 56}")


def compact_tool_result(text: str, max_len: int = 900) -> str:
    text = re.sub(
        r"!\[[^\]]*\]\(data:image/[^)]+\)",
        "[图片已省略]",
        text,
    )
    if len(text) <= max_len:
        return text
    return text[:max_len] + "\n…（已截断）"


class HubStreamPrinter:
    """Hub 全链路事件打印。"""

    def __init__(self) -> None:
        self._phase = ""
        self._llm_round = 0
        self._need_round_header = True
        self._streaming = False
        self._plan_streaming = False
        self._step_streaming = False
        self._execute_order = 0
        self._suppress_react_final = False
        self._seen_react_answer = False

    def _end_stream_line(self) -> None:
        if self._streaming or self._plan_streaming or self._step_streaming:
            print()
            self._streaming = False
            self._plan_streaming = False
            self._step_streaming = False

    def handle(self, ev: AgentEvent) -> None:
        if isinstance(ev, HubPhaseEvent):
            self._end_stream_line()
            self._phase = ev.phase
            if ev.phase == "react":
                print_section("Hub · 阶段 1/3 · ReAct 意图澄清")
            elif ev.phase == "plan":
                print_section("Hub · 阶段 2/3 · PlanExecute")
                self._suppress_react_final = True
            elif ev.phase == "revision":
                print_section("Hub · 修订重跑（Reflection 打回）")
                self._execute_order = 0
            elif ev.phase == "reflection":
                print_section("Hub · 阶段 3/3 · Reflection 质量审查")
            return

        if isinstance(ev, HubTurnCompleteEvent):
            self._end_stream_line()
            self._print_turn_complete(ev)
            return

        if self._phase == "react":
            self._handle_react(ev)
        elif self._phase in ("plan", "revision"):
            self._handle_plan(ev)
        elif self._phase == "reflection":
            self._handle_reflection(ev)
        elif isinstance(ev, ErrorEvent):
            print(f"\n✗ {ev.error}", file=sys.stderr)

    def _print_turn_complete(self, ev: HubTurnCompleteEvent) -> None:
        print_section("Hub · 本轮结束 · 对用户展示")
        print(f"  路由: {ev.route}")
        final = (ev.final_user_message or ev.user_reply or "").strip()
        print(f"\n{final or '（空）'}")
        if ev.deliverable and ev.deliverable != ev.delivery_summary:
            print(f"\n── （调试）原始 deliverable ──\n")
            print(compact_tool_result(ev.deliverable, max_len=600))

    def _handle_react(self, ev: AgentEvent) -> None:
        if isinstance(ev, TextDeltaEvent):
            if self._need_round_header:
                self._need_round_header = False
                self._llm_round += 1
                print(f"\n{'─' * 56}")
                print(f"▶ ReAct 第 {self._llm_round} 轮（流式）")
                print(f"{'─' * 56}\n")
            sys.stdout.write(ev.delta)
            sys.stdout.flush()
            self._streaming = True
            self._seen_react_answer = True
            return
        self._end_stream_line()
        if isinstance(ev, IntentOutcomeEvent):
            if not ev.is_clear:
                route = "→ 继续澄清（不进 Plan）"
            elif ev.should_invoke_plan:
                route = "→ PlanExecute"
            else:
                route = "→ 直接回复（不进 Plan）"
            print(f"\n▣ 结构化意图  is_clear={ev.is_clear}  {route}")
            return
        if isinstance(ev, ToolCallEvent):
            print(f"\n┌─ 工具调用 · {ev.tool_name}")
            print(json.dumps(ev.args, ensure_ascii=False, indent=2))
            print("└─")
            return
        if isinstance(ev, ToolResultEvent):
            print(f"\n┌─ 工具返回 · {ev.tool_name}")
            print(compact_tool_result(ev.result))
            print("└─")
            self._need_round_header = True
            return
        if isinstance(ev, MemoryConsolidatedEvent):
            print("\n▣ 长期记忆提炼（ReAct 回合结束）")
            return
        if isinstance(ev, FinalAnswerEvent):
            if self._suppress_react_final or self._seen_react_answer:
                return
            print("\n▣ ReAct 最终回复")
            print(ev.content or "(空)")
            return
        if isinstance(ev, RunStatsEvent):
            print(f"\n  ReAct 统计: 轮次={ev.steps} 耗时={ev.elapsed_ms}ms")
            return
        if isinstance(ev, ErrorEvent):
            print(f"\n✗ {ev.error}", file=sys.stderr)

    def _handle_plan(self, ev: AgentEvent) -> None:
        if isinstance(ev, PlanReadyEvent):
            self._end_stream_line()
            plan = ev.plan
            if isinstance(plan, ExecutionPlan):
                print(f"\n  Plan 解析完成：{len(plan.steps)} 步")
            return
        if isinstance(ev, PlanCreatedEvent):
            self._end_stream_line()
            print(f"\n  Execute：{len(ev.steps)} 步\n")
            return
        if isinstance(ev, StepStartEvent):
            self._end_stream_line()
            self._execute_order += 1
            print(f"▶ [{self._execute_order}] step {ev.step_id} · {ev.agent_type}")
            print(f"  {ev.description}\n")
            return
        if isinstance(ev, StepOutputDeltaEvent):
            sys.stdout.write(ev.delta)
            sys.stdout.flush()
            self._step_streaming = True
            return
        if isinstance(ev, StepCompleteEvent):
            self._end_stream_line()
            print(f"  ✓ step {ev.step_id} 完成\n")
            return
        if isinstance(ev, StepErrorEvent):
            self._end_stream_line()
            print(f"  ✗ step {ev.step_id}: {ev.error}", file=sys.stderr)
            return
        if isinstance(ev, ExecutionResultEvent):
            self._end_stream_line()
            return
        if isinstance(ev, RunStatsEvent) and self._phase in ("plan", "revision"):
            label = "修订" if self._phase == "revision" else "PlanExecute"
            print(f"  {label} 耗时: {ev.elapsed_ms} ms")
            return
        if isinstance(ev, ErrorEvent):
            print(f"\n✗ {ev.error}", file=sys.stderr)

    def _handle_reflection(self, ev: AgentEvent) -> None:
        if isinstance(ev, ReflectionStartEvent):
            print(f"  审查 trace 步数: {ev.step_count}\n")
            return
        if isinstance(ev, ReflectionTextDeltaEvent):
            sys.stdout.write(ev.delta)
            sys.stdout.flush()
            self._streaming = True
            return
        if isinstance(ev, ReflectionCompleteEvent):
            self._end_stream_line()
            v = ev.verdict
            print(f"\n  Reflection 完成 · passed={v.passed} · {ev.elapsed_ms}ms")
            return
        if isinstance(ev, ErrorEvent):
            print(f"\n✗ {ev.error}", file=sys.stderr)


async def run_turn(hub: CortexHub, query: str) -> None:
    print(f"用户: {query}\n")
    printer = HubStreamPrinter()
    async for ev in hub.run_turn_stream(query):
        printer.handle(ev)
    outcome = hub.get_last_outcome()
    if outcome:
        rev = (
            f" revision_rounds={outcome.revision_rounds}"
            if outcome.revision_rounds
            else ""
        )
        print(f"\n[hub] route={outcome.route}{rev}")
    print()


async def run_repl(hub: CortexHub) -> None:
    print_section("Hub REPL · 同 session 多轮（澄清后自动 Plan）")
    print("输入 quit 退出")
    print("（同一 session_id，ReAct 会加载上一轮对话历史）\n")
    while True:
        try:
            sys.stdout.write("用户> ")
            sys.stdout.flush()
            line = input().strip()
        except (EOFError, KeyboardInterrupt):
            print()
            break
        if not line or line.lower() in ("quit", "exit", "q"):
            break
        await run_turn(hub, line)
