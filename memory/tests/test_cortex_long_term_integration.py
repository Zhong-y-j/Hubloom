"""CortexAgent 长期记忆读取 + Qdrant 集成 smoke test。

验证编排层：batch 写入 Qdrant → ``_recall_long_term_context`` → ContextAssembler → messages 含 ``[MEMORY]``。

运行::

    PYTHONPATH=. uv run python -m memory.tests.test_cortex_long_term_integration
    PYTHONPATH=. uv run python -m memory.tests.test_cortex_long_term_integration --route chat
    PYTHONPATH=. uv run python -m memory.tests.test_cortex_long_term_integration --route thought
    PYTHONPATH=. uv run python -m memory.tests.test_cortex_long_term_integration --route all

需要 ``OPENAI_API_KEY``、``QDRANT_URL``（及可选 ``QDRANT_API_KEY``）。
"""

from __future__ import annotations

import argparse
import asyncio
from typing import Any
from unittest.mock import AsyncMock, MagicMock

from core.factory import create_llm
from core.models import Message, Role
from memory.batch_consolidator import MemoryBatchConsolidator
from memory.factory import create_memory_manager
from memory.memory_context import MemoryRecallContext
from memory.store.conversation_sqlite_store import ConversationMessageRecord
from observability import setup_log
from tools.base import BaseTool
from tools.registry import ToolRegistry

from agents.assessor import AssessResult
from agents.cortex_agent import CortexAgent, Route
from agents.events import FinalAnswerEvent, ThoughtDeltaEvent


NAMESPACE = "mem:test_cortex_ltm:default"
SESSION_ID = "test_cortex_ltm"
QUERY = "帮我查一下当前库存"


class StubInventoryTool(BaseTool):
    """集成测试用库存工具，避免依赖 MCP。"""

    name = "list_inventory"
    description = (
        "查询各仓库当前库存数量。若未指定 warehouse，返回可选仓库列表并提示需补充参数。"
    )
    parameters: dict[str, Any] = {
        "type": "object",
        "properties": {
            "warehouse": {
                "type": "string",
                "description": "仓库名称或编号，如 A",
            },
        },
        "required": [],
    }

    async def execute(self, warehouse: str = "", **_: Any) -> str:
        wh = (warehouse or "").strip()
        if not wh:
            return '{"warehouses": ["A", "B"], "message": "请指定 warehouse 参数"}'
        return f'{{"warehouse": "{wh}", "available": 120, "pending": 5}}'


def _inventory_records() -> list[ConversationMessageRecord]:
    return [
        ConversationMessageRecord(
            id="c1",
            message=Message(role=Role.USER, content="帮我查当前库存"),
        ),
        ConversationMessageRecord(
            id="c2",
            message=Message(
                role=Role.ASSISTANT,
                content="好的，我来查询库存。",
            ),
        ),
        ConversationMessageRecord(
            id="c3",
            message=Message(role=Role.USER, content="仓库 A 的"),
        ),
        ConversationMessageRecord(
            id="c4",
            message=Message(
                role=Role.ASSISTANT,
                content="仓库 A 当前可用库存 120 件。",
            ),
        ),
    ]


def _mock_assessor(*, need_deep_think: bool, query: str) -> MagicMock:
    assessor = MagicMock()
    route = "thought" if need_deep_think else "chat"
    assessor.evaluate = AsyncMock(
        return_value=AssessResult(
            need_deep_think=need_deep_think,
            reason=f"integration: force {route} path",
            task=query,
        )
    )
    return assessor


async def _seed_via_batch_consolidator(mem) -> None:
    """模拟离线 consolidator：会话片段 → LLM 抽取 → Qdrant。"""
    consolidator = MemoryBatchConsolidator(mem, create_llm())
    result = await consolidator.consolidate_segment(
        NAMESPACE,
        _inventory_records(),
        route="thought",
    )
    print("--- batch consolidate (seed) ---")
    print("skipped:", result.skipped)
    print("cases:", len(result.cases_written))
    print("rules:", len(result.semantic_rules_written))
    if result.error:
        raise RuntimeError(f"batch consolidate failed: {result.error}")
    if not result.cases_written and not result.semantic_rules_written:
        raise RuntimeError("batch consolidate wrote nothing")


async def _recall_long_term(agent: CortexAgent, query: str) -> MemoryRecallContext:
    memory_ctx = await agent._recall_long_term_context(query)
    hits = memory_ctx.memories or []
    print("--- cortex recall ---")
    print("hybrid hits:", len(hits))
    for i, row in enumerate(hits, 1):
        preview = str(row.get("content", ""))[:100].replace("\n", " ")
        print(f"  [{i}] {row.get('memory_type')} score={row.get('score'):.2f} {preview!r}")
    if not hits:
        raise AssertionError("长期记忆召回为空，请检查 Qdrant 与 namespace")
    return memory_ctx


def _print_assembled(route: Route, messages: list[Message]) -> None:
    label = route.value.upper()
    print(f"--- assembled messages ({label}) ---")
    for m in messages:
        tag = m.role.value
        body = (m.content or "").replace("\n", " ")[:120]
        print(f"  {tag}: {body!r}")


def _assert_memory_block(messages: list[Message], route: Route) -> None:
    memory_blocks = [
        m for m in messages if m.role == Role.SYSTEM and "[MEMORY]" in m.content
    ]
    if not memory_blocks:
        raise AssertionError(f"{route.value} 装配结果缺少 [MEMORY] SYSTEM 块")


async def _verify_assemble(
    agent: CortexAgent,
    query: str,
    memory_ctx: MemoryRecallContext,
    route: Route,
) -> list[Message]:
    messages = agent._assemble_agent_messages(route, query, [], memory_ctx)
    _print_assembled(route, messages)
    _assert_memory_block(messages, route)
    return messages


async def _verify_stream(
    agent: CortexAgent,
    query: str,
    route: Route,
) -> str:
    label = route.value.upper()
    print(f"--- cortex run_stream ({label}) ---")
    final = ""
    thinking_preview = ""
    async for ev in agent.run_stream(query):
        if isinstance(ev, ThoughtDeltaEvent) and ev.delta:
            thinking_preview += ev.delta
        if isinstance(ev, FinalAnswerEvent) and ev.content:
            final = ev.content
    if route == Route.THOUGHT and thinking_preview:
        print("thinking_preview:", thinking_preview[:200].replace("\n", " "))
    print("final_answer:", final[:300].replace("\n", " "))
    if not final.strip():
        raise AssertionError(f"{label} 路径未产出最终回复")
    return final


async def _run_chat_branch(agent: CortexAgent, query: str) -> None:
    agent.assessor = _mock_assessor(need_deep_think=False, query=query)
    memory_ctx = await _recall_long_term(agent, query)
    await _verify_assemble(agent, query, memory_ctx, Route.CHAT)
    await _verify_stream(agent, query, Route.CHAT)
    print("✓ CHAT branch OK")


async def _run_thought_branch(agent: CortexAgent, query: str) -> None:
    agent.assessor = _mock_assessor(need_deep_think=True, query=query)
    memory_ctx = await _recall_long_term(agent, query)
    await _verify_assemble(agent, query, memory_ctx, Route.THOUGHT)
    await _verify_stream(agent, query, Route.THOUGHT)
    print("✓ THOUGHT branch OK")


def _build_agent() -> CortexAgent:
    tools = ToolRegistry.from_tools([StubInventoryTool()])
    return CortexAgent(
        create_llm(),
        tools=tools,
        session_id=SESSION_ID,
        assessor=_mock_assessor(need_deep_think=False, query=QUERY),
        enable_long_term_memory=True,
        include_graph_memory=False,
        graph_backend="none",
        long_term_top_k=5,
    )


async def main(route: str = "all") -> None:
    setup_log()

    mem = create_memory_manager(namespace=NAMESPACE, graph_backend="none")
    await mem.clear_all()
    await _seed_via_batch_consolidator(mem)

    agent = _build_agent()

    if route in ("chat", "all"):
        await _run_chat_branch(agent, QUERY)
    if route in ("thought", "all"):
        await _run_thought_branch(agent, QUERY)

    print("\n✓ cortex long-term memory integration OK")


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--route",
        choices=("chat", "thought", "all"),
        default="all",
        help="要运行的路径分支（默认 all：CHAT + THOUGHT）",
    )
    return parser.parse_args()


if __name__ == "__main__":
    args = _parse_args()
    asyncio.run(main(route=args.route))
