"""Hub 端到端冒烟：ReAct → PlanExecute → Reflection。

运行：
    PYTHONPATH=. uv run agents/test_hub.py
    PYTHONPATH=. uv run agents/test_hub.py --repl
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
import sys
import warnings

from agents import ReActAgent
from agents.default_registry import build_default_registry
from agents.events import (
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
    PlanTextDeltaEvent,
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
from agents.intent import StructuredIntent
from agents.plan_execute import LLMPlanGenerator, PlanExecuteAgent
from agents.plan_models import ExecutionPlan
from agents.reflection import ReflectionAgent
from agents.specialists import RegistryStepDelegate
from context import ContextAssembler
from core import create_llm
from memory.embedders.openai_embedder import OpenAIEmbedder
from memory.factory import create_memory_manager
from memory.store.conversation_sqlite_store import ConversationSQLitesStore
from retrieval.knowledge_base import KnowledgeBase
from tools import ToolRegistry
from tools.builtin import SearchDocumentsTool, SearchMemoryTool

warnings.filterwarnings(
    "ignore",
    message="Failed to obtain server version",
    category=UserWarning,
)

DEFAULT_QUERY = (
    "帮我写一份 5 万元的软件开发合同，要有源代码归属和付款节点，"
    "技术规格和法律条款都要。"
)


def _print_section(title: str) -> None:
    print(f"\n{'═' * 56}")
    print(f"▣ {title}")
    print(f"{'═' * 56}")


def _compact_tool_result(text: str, max_len: int = 900) -> str:
    text = re.sub(
        r"!\[[^\]]*\]\(data:image/[^)]+\)",
        "[图片已省略]",
        text,
    )
    if len(text) <= max_len:
        return text
    return text[:max_len] + "\n…（已截断）"


def _build_hub(*, run_reflection: bool) -> CortexHub:
    llm = create_llm()
    namespace = "mem:hub_test:default"
    conversation_store = ConversationSQLitesStore("data/memory.db")
    kb = KnowledgeBase(embedder=OpenAIEmbedder(), persist_dir="data/knowledge_db")
    memory_manager = create_memory_manager(namespace=namespace)
    tools = ToolRegistry.from_tools(
        [
            SearchDocumentsTool(kb),
            SearchMemoryTool(memory_manager),
        ]
    )
    react = ReActAgent(
        llm,
        tools,
        memory_manager=memory_manager,
        conversation_store=conversation_store,
        session_id=namespace,
        context_assembler=ContextAssembler(),
        knowledge_base=kb,
        consolidate_memory=True,
    )
    registry = build_default_registry()
    plan_execute = PlanExecuteAgent(
        llm,
        plan_generator=LLMPlanGenerator(llm, registry=registry),
        registry=registry,
        step_delegate=RegistryStepDelegate(llm),
    )
    reflection = ReflectionAgent(llm) if run_reflection else None
    max_revision = int(os.getenv("HUB_MAX_REVISION_ROUNDS", "1"))
    return CortexHub(
        react,
        plan_execute,
        reflection,
        run_reflection=run_reflection,
        stream_plan_separately=True,
        max_revision_rounds=max_revision,
    )


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
                _print_section("Hub · 阶段 1/3 · ReAct 意图澄清")
            elif ev.phase == "plan":
                _print_section("Hub · 阶段 2/3 · PlanExecute")
                self._suppress_react_final = True
            elif ev.phase == "revision":
                _print_section("Hub · 修订重跑（Reflection 打回）")
                self._execute_order = 0
            elif ev.phase == "reflection":
                _print_section("Hub · 阶段 3/3 · Reflection 质量审查")
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
        _print_section("Hub · 本轮结束 · 对用户展示")
        print(f"  路由: {ev.route}")
        print(f"\n── ① 确认回复（user_reply，来自 ReAct）──\n")
        print(ev.user_reply or "（空）")
        if ev.deliverable:
            print(f"\n── ② 任务交付物（deliverable，来自 PlanExecute）──\n")
            print(ev.deliverable)
        else:
            print("\n── ② 任务交付物 ──\n（本轮无 Plan 产出）")
        if ev.reflection_verdict is not None:
            v = ev.reflection_verdict
            print(f"\n── ③ 质量审查（Reflection）──")
            print(f"  passed: {v.passed}")
            print(f"  summary: {v.summary}")
            if not v.passed:
                print(f"  recommendation: {v.recommendation or '（无）'}")

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
            print(_compact_tool_result(ev.result))
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


async def _run_once(hub: CortexHub, query: str) -> None:
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


async def _run_repl(hub: CortexHub) -> None:
    _print_section("Hub REPL · 同 session 多轮（澄清后自动 Plan）")
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
        await _run_once(hub, line)


async def main() -> None:
    parser = argparse.ArgumentParser(description="Cortex Hub 冒烟")
    parser.add_argument(
        "--repl",
        action="store_true",
        help="多轮对话模式（同一 ReAct session）",
    )
    parser.add_argument(
        "query",
        nargs="?",
        default=DEFAULT_QUERY,
        help="单轮用户输入",
    )
    args = parser.parse_args()

    run_reflection = os.getenv("RUN_REFLECTION", "1").lower() not in (
        "0",
        "false",
        "no",
    )
    hub = _build_hub(run_reflection=run_reflection)

    if args.repl:
        await _run_repl(hub)
    else:
        await _run_once(hub, args.query)


if __name__ == "__main__":
    asyncio.run(main())
