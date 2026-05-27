"""MemoryContextProvider + ContextAssembler：查看交给 Agent 前的 messages 格式。

运行（需 Qdrant + 嵌入；Neo4j 可选）::

    PYTHONPATH=. uv run python -m memory.test_memory_context

无图记忆::

    PYTHONPATH=. uv run python -m memory.test_memory_context --no-graph

打印每条 message 全文（不截断）::

    PYTHONPATH=. uv run python -m memory.test_memory_context --full
"""

from __future__ import annotations

import argparse
import asyncio

from core.models import Message, Role
from memory.context import ContextAssembler
from memory.factory import create_memory_manager
from memory.memory_context import MemoryContextProvider
from observability import setup_log

NAMESPACE = "mem:tester_id:default"
QUERY = "陈艳 合同项目A 付款 违约"

SYSTEM_PROMPT = (
    "你是 Agent Cortex 智能助手。\n"
    "结合 [MEMORY]、[GRAPH] 与对话历史回答用户；若无相关内容可说明未检索到。"
)


def _print_messages(messages: list[Message], *, full: bool) -> None:
    print(f"\n{'=' * 60}")
    print(f"  交给 LLM 的 messages（共 {len(messages)} 条）")
    print(f"{'=' * 60}")
    for i, msg in enumerate(messages):
        content = str(msg.content or "")
        print(f"\n--- [{i}] role={msg.role.value} ---")
        if full:
            print(content)
        else:
            if len(content) <= 500:
                print(content)
            else:
                print(content[:500])
                print(f"\n... (共 {len(content)} 字符，加 --full 看全文)")


async def main(*, no_graph: bool, full: bool) -> None:
    setup_log()

    mem = create_memory_manager(
        namespace=NAMESPACE,
        graph_backend="none" if no_graph else "neo4j",
    )
    provider = MemoryContextProvider(
        mem,
        hybrid_top_k=5,
        include_associative=not no_graph,
    )

    print("--- 1. MemoryContextProvider 召回 ---")
    print("namespace:", NAMESPACE)
    print("query:", QUERY)

    ctx = await provider.recall_for_context(QUERY)
    print(f"memories: {len(ctx.memories)} 条")
    for row in ctx.memories:
        print(
            f"  - [{row.get('memory_type')}] "
            f"score={row.get('score', 0):.2f} | {row.get('content', '')[:60]}"
        )
    print("graph_summary:", "有" if ctx.graph_summary else "无")

    # 对话历史（与 ReAct 一致：从 conversation 取最近 N 条）
    conv = await mem.recall(memory_type="conversation", top_k=10)
    histories = conv.messages or []

    print("\n--- 2. ContextAssembler 装配（ReAct 同款结构）---")
    asm = ContextAssembler(max_tokens=3000, min_relevance=0.3)
    messages = asm.assemble(
        system_prompt=SYSTEM_PROMPT,
        memories=ctx.memories,
        documents=None,
        histories=histories,
        current_task=QUERY,
        graph_summary=ctx.graph_summary,
    )

    _print_messages(messages, full=full)

    print("\n--- 结构说明 ---")
    print("[0] system     → 人设/规则")
    print("[?] system     → [MEMORY]...[/MEMORY]  （有长期记忆时）")
    print("[?] system     → [GRAPH]...[/GRAPH]    （有图摘要时）")
    print("[?] user/assistant → 最近对话轮次")
    print("[最后] user    → 当前用户输入（current_task）")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--no-graph", action="store_true", help="不启用 Neo4j 图召回")
    parser.add_argument("--full", action="store_true", help="打印每条 message 全文")
    args = parser.parse_args()
    asyncio.run(main(no_graph=args.no_graph, full=args.full))
