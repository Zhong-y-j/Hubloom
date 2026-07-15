"""MemoryManager 统一接口验证。

运行::

    PYTHONPATH=. uv run python -m memory.tests.test_memory_manager

需要：
- Qdrant（``QDRANT_URL`` / ``QDRANT_API_KEY``）
- Neo4j Aura（``NEO4J_URI`` / ``NEO4J_PASSWORD`` 等）
- ``OPENAI_API_KEY``（向量嵌入）
"""

from __future__ import annotations

import asyncio

from core.models import Message, Role
from memory.factory import create_memory_manager
from observability import setup_log


async def main() -> None:
    setup_log()
    namespace = "mem:tester_id:default"

    mem = create_memory_manager(namespace=namespace)
    await mem.clear_all()
    await mem.remember(memory_type="episodic", content="用户在上海")
    await mem.remember(memory_type="semantic", content="喜欢唱歌跳舞打篮球")

    await mem.remember(
        memory_type="associative",
        content="居住",
        metadata={
            "from_name": "陈艳",
            "to_name": "上海",
            "relation_label": "居住",
            "from_entity_type": "person",
            "to_entity_type": "location",
        },
    )

    await mem.remember(
        memory_type="conversation",
        message=Message(role=Role.USER, content="你好"),
    )
    await mem.remember(
        memory_type="conversation",
        message=Message(role=Role.ASSISTANT, content="你好，有什么可以帮你？"),
    )

    conv = await mem.recall(memory_type="conversation", top_k=10)
    print("conversation:", [m.content for m in conv.messages or []])

    long_term = await mem.recall(query="上海", mode="hybrid", top_k=5)
    print("long_term:", [i.content for i in long_term.items or []])

    graph_result = await mem.recall(
        memory_type="associative",
        query="陈艳",
        top_k=10,
        filters={"include_memory_refs": False},
    )
    g = graph_result.graph
    if g and g.seed:
        print("associative seed:", g.seed.name, g.seed.entity_type)
        print("associative neighbors:", [e.name for e in g.entities])
        print(
            "associative relations:",
            [f"{r.from_name}-[{r.relation_label}]->{r.to_name}" for r in g.relations],
        )
    else:
        print("associative: (empty)")

    print("handlers:", list(mem.handlers.keys()))


if __name__ == "__main__":
    asyncio.run(main())
