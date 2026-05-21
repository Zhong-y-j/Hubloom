"""MemoryManager 统一接口验证。运行：uv run python -m memory.test_memory_manager

需要：
- 本地 Qdrant（默认 http://localhost:6333），例如 ``docker run -p 6333:6333 qdrant/qdrant``
- ``OPENAI_API_KEY``（向量嵌入）
"""

from __future__ import annotations

import asyncio
import os

from core.models import Message, Role
from memory.factory import create_memory_manager


async def main() -> None:
    namespace = "mem:tester_id:default"

    mem = create_memory_manager(namespace=namespace)

    await mem.remember(memory_type="episodic", content="用户在上海")
    await mem.remember(memory_type="semantic", content="喜欢唱歌跳舞打篮球")
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

    long_term = await mem.recall(query="拉屎", top_k=5)
    print("long_term:", [i.content for i in long_term.items or []])

    print("handlers:", list(mem.handlers.keys()))


if __name__ == "__main__":
    asyncio.run(main())
