"""MemoryContextProvider + ContextAssembler：查看交给 Agent 前的 messages 格式。

运行（需 Qdrant + 嵌入；Neo4j 可选）::

    PYTHONPATH=. uv run python -m memory.tests.test_memory_context
"""

from __future__ import annotations

import asyncio

from memory.context import ContextAssembler
from memory.factory import create_memory_manager
from memory.memory_context import MemoryContextProvider
from observability import setup_log

NAMESPACE = "mem:tester_id:default"
QUERY = "张三 合同项目A 付款 违约"

SYSTEM_PROMPT = (
    "你是 Hubloom 智能助手。\n"
    "结合 [MEMORY]、[GRAPH] 与对话历史回答用户；若无相关内容可说明未检索到。"
)


async def main() -> None:
    setup_log()

    mem = create_memory_manager(namespace=NAMESPACE, graph_backend="none")
    provider = MemoryContextProvider(
        mem,
        hybrid_top_k=5,
        include_associative=True,
    )

    print("--- 1. MemoryContextProvider 召回 ---")
    print("namespace:", NAMESPACE)
    print("query:", QUERY)

    ctx = await provider.recall_for_context(QUERY)
    print(ctx)
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
    print(messages)


if __name__ == "__main__":
    asyncio.run(main())
