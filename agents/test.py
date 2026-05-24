"""ReAct Agent 冒烟：可读地打印推理、工具调用与最终回答。"""

from __future__ import annotations

import asyncio
import json
import re
import sys

from agents import ReActAgent
from agents.events import (
    AgentEvent,
    ErrorEvent,
    FinalAnswerEvent,
    IntentOutcomeEvent,
    MemoryConsolidatedEvent,
    RunStatsEvent,
    TextDeltaEvent,
    ToolCallEvent,
    ToolResultEvent,
)
from agents.intent import StructuredIntent
from context import ContextAssembler
from core import create_llm
from memory.embedders.openai_embedder import OpenAIEmbedder
from memory.factory import create_memory_manager
from retrieval.knowledge_base import KnowledgeBase
from tools import ToolRegistry
from tools.builtin import SearchDocumentsTool, SearchMemoryTool
from memory.store.conversation_sqlite_store import ConversationSQLitesStore

conversation_store = ConversationSQLitesStore("data/memory.db")
kb = KnowledgeBase(embedder=OpenAIEmbedder(), persist_dir="data/knowledge_db")
namespace = "mem:tester_id:default"
memory_manager = create_memory_manager(namespace=namespace)
tools = ToolRegistry.from_tools(
    [
        SearchDocumentsTool(kb),
        SearchMemoryTool(memory_manager),
    ]
)
agent = ReActAgent(
    create_llm(),
    tools,
    memory_manager=memory_manager,
    conversation_store=conversation_store,
    session_id=namespace,
    context_assembler=ContextAssembler(),
    knowledge_base=kb,
    consolidate_memory=True,
)


def _compact_tool_result(text: str, max_len: int = 900) -> str:
    """压缩工具返回：去掉 base64 图片，过长则截断。"""
    cleaned = re.sub(
        r"!\[[^\]]*\]\(data:image[^)]+\)",
        "[图片已省略]",
        text,
    )
    cleaned = re.sub(r"base64\.\.\.", "[base64省略]", cleaned)
    if len(cleaned) <= max_len:
        return cleaned
    return cleaned[:max_len] + f"\n…（其余 {len(cleaned) - max_len} 字已截断）"


class AgentRunPrinter:
    """把 AgentEvent 转成终端可读 trace。"""

    def __init__(self, *, query: str) -> None:
        self._query = query
        self._llm_round = 0
        self._need_round_header = True
        self._streaming = False

    def _begin_llm_round(self) -> None:
        if not self._need_round_header:
            return
        self._need_round_header = False
        self._llm_round += 1
        print(f"\n{'─' * 56}")
        print(f"▶ 第 {self._llm_round} 轮 · 模型推理 / 回复（流式）")
        print(f"{'─' * 56}\n")

    def _end_stream_line(self) -> None:
        if self._streaming:
            print()
            self._streaming = False

    def handle(self, ev: AgentEvent) -> None:
        if isinstance(ev, TextDeltaEvent):
            self._begin_llm_round()
            sys.stdout.write(ev.delta)
            sys.stdout.flush()
            self._streaming = True
            return

        self._end_stream_line()

        if isinstance(ev, ToolCallEvent):
            print(f"\n┌─ 工具调用 ─────────────────────────────────────")
            print(f"│ 工具: {ev.tool_name}")
            print(f"│ call_id: {ev.call_id}")
            print("│ 参数:")
            for line in json.dumps(ev.args, ensure_ascii=False, indent=2).splitlines():
                print(f"│   {line}")
            print("└────────────────────────────────────────────────")
            return

        if isinstance(ev, ToolResultEvent):
            status = "失败" if ev.is_error else "成功"
            print(f"\n┌─ 工具返回 · {status} ─────────────────────────────────")
            print(f"│ 工具: {ev.tool_name}")
            print(f"│ call_id: {ev.call_id}")
            print("├─ 结果预览 ─")
            body = _compact_tool_result(ev.result)
            for line in body.splitlines():
                print(f"│ {line}")
            print("└────────────────────────────────────────────────")
            self._need_round_header = True
            return

        if isinstance(ev, RunStatsEvent):
            print(f"\n{'═' * 56}")
            print("▣ 运行统计")
            print(
                f"  LLM 轮次: {ev.steps}  |  工具调用: {ev.tool_calls}  |  工具失败: {ev.tool_errors}"
            )
            print(f"  耗时: {ev.elapsed_ms} ms")
            print(f"{'═' * 56}")
            return

        if isinstance(ev, IntentOutcomeEvent):
            intent: StructuredIntent = ev.intent
            print(f"\n{'═' * 56}")
            route = (
                "→ PlanExecute" if ev.should_invoke_plan else "→ 直接回复（不进 Plan）"
            )
            print(
                f"▣ 结构化意图  is_clear={ev.is_clear}  "
                f"intent={intent.intent!r}  {route}"
            )
            print(f"{'═' * 56}")
            print(json.dumps(intent.to_dict(), ensure_ascii=False, indent=2))
            return

        if isinstance(ev, MemoryConsolidatedEvent):
            print(f"\n{'═' * 56}")
            print("▣ 长期记忆提炼写入")
            print(f"{'═' * 56}")
            if ev.error:
                print(f"  错误: {ev.error}")
            elif ev.skipped:
                print("  （本轮无可写入的长期记忆）")
            else:
                if ev.episodic:
                    print("  情景:", ev.episodic)
                if ev.semantic:
                    print("  语义:", ev.semantic)
                if ev.relations:
                    print("  关系:", ev.relations)
                if ev.links:
                    print("  图↔向量链接:", ev.links)
            return

        if isinstance(ev, FinalAnswerEvent):
            print(f"\n{'═' * 56}")
            print("▣ 用户可见回复")
            print(f"{'═' * 56}\n")
            print(ev.content or "(空)")
            if ev.intent is not None:
                print("\n（intent 已解析，见上方「结构化意图」块）")
            if ev.usage:
                u = ev.usage
                print(
                    f"\n[token] prompt={u.prompt_tokens} "
                    f"completion={u.completion_tokens} total={u.total_tokens}"
                )
            return

        if isinstance(ev, ErrorEvent):
            print(f"\n✗ 错误: {ev.error}", file=sys.stderr)
            return

        print(ev)


async def main() -> None:
    query = (
        "张三是我的员工上了一个月的班几乎天天迟到，还没有过试用期，我想要开除他可以吗"
    )
    print(f"用户问题: {query}\n")
    printer = AgentRunPrinter(query=query)
    async for ev in agent.run_stream(query):
        printer.handle(ev)
    intent = agent.get_last_intent()
    if intent:
        plan = "进 PlanExecute" if intent.should_invoke_plan() else "不进 Plan"
        print(
            f"\n[hub] get_last_intent() → is_clear={intent.is_clear}, "
            f"intent={intent.intent!r}, {plan}"
        )
    print()


if __name__ == "__main__":
    asyncio.run(main())
