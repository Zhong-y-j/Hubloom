"""Hub 终端交互：事件打印与单轮 / REPL 运行。"""

from __future__ import annotations

import json
import re
import sys

from agents.core.events import (
    AgentEvent,
    ErrorEvent,
    FinalAnswerEvent,
    HubPhaseEvent,
    HubTurnCompleteEvent,
    IntentOutcomeEvent,
    MemoryConsolidatedEvent,
    RunStatsEvent,
    TextDeltaEvent,
    ToolCallEvent,
    ToolResultEvent,
)
from agents.hub import CortexHub


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
    """Hub ReAct 事件打印。"""

    def __init__(self) -> None:
        self._phase = ""
        self._llm_round = 0
        self._need_round_header = True
        self._streaming = False
        self._seen_react_answer = False

    def _end_stream_line(self) -> None:
        if self._streaming:
            print()
            self._streaming = False

    def handle(self, ev: AgentEvent) -> None:
        if isinstance(ev, HubPhaseEvent):
            self._end_stream_line()
            self._phase = ev.phase
            if ev.phase == "react":
                print_section("Hub · ReAct")
            return

        if isinstance(ev, HubTurnCompleteEvent):
            self._end_stream_line()
            self._print_turn_complete(ev)
            return

        if self._phase == "react":
            self._handle_react(ev)
        elif isinstance(ev, ErrorEvent):
            print(f"\n✗ {ev.error}", file=sys.stderr)

    def _print_turn_complete(self, ev: HubTurnCompleteEvent) -> None:
        print_section("Hub · 本轮结束")
        print(f"  路由: {ev.route}")
        final = (ev.final_user_message or ev.user_reply or "").strip()
        print(f"\n{final or '（空）'}")

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
            route = "→ 继续澄清" if not ev.is_clear else "→ 完成本轮"
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
            if self._seen_react_answer:
                return
            print("\n▣ ReAct 最终回复")
            print(ev.content or "(空)")
            return
        if isinstance(ev, RunStatsEvent):
            print(f"\n  ReAct 统计: 轮次={ev.steps} 耗时={ev.elapsed_ms}ms")
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
        print(f"\n[hub] route={outcome.route}")
    print()


async def run_repl(hub: CortexHub) -> None:
    print_section("Hub REPL · 同 session 多轮")
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
