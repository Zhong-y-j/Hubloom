"""MemoryManager 统一接口验证。运行：uv run python -m memory.test_memory_manager"""

from __future__ import annotations

import asyncio
from pathlib import Path

from core.models import Message, Role
from memory.embedders import OpenAIEmbedder
from memory.handlers import (
    ConversationHandler,
    EpisodicHandler,
    MemoryHandler,
    SemanticHandler,
)
from memory.manager import MemoryManager
from memory.store.conversation_sqlite_store import ConversationSQLitesStore
from memory.store.episodic_sqlite_store import EpisodicSQLiteStore
from memory.store.semantic_sqlite_store import SemanticSQLiteStore


async def main() -> None:
    db_path = "data/memory_test.db"
    namespace = "mem:tester_id:default"

    Path(db_path).parent.mkdir(parents=True, exist_ok=True)

    # 1.实例化存储
    episodic_store = EpisodicSQLiteStore(db_path)
    semantic_store = SemanticSQLiteStore(db_path)
    conversation_store = ConversationSQLitesStore(db_path)

    print(f"已建表: episodic_memory, semantic_memory, conversation_memory")

    # 2.实例化处理器
    handlers: dict[str, MemoryHandler] = {
        "episodic": EpisodicHandler(store=episodic_store, namespace=namespace),
        "semantic": SemanticHandler(
            store=semantic_store,
            embedder=OpenAIEmbedder(),
            namespace=namespace,
        ),
        "conversation": ConversationHandler(
            store=conversation_store,
            session_id=namespace,
        ),
    }

    mem = MemoryManager(handlers=handlers)

    # 统一 remember
    await mem.remember(memory_type="episodic", content="用户偏好简洁回复")
    await mem.remember(memory_type="semantic", content="用户偏好简洁回复，使用向量检索")
    await mem.remember(
        memory_type="conversation",
        message=Message(role=Role.USER, content="你好"),
    )
    await mem.remember(
        memory_type="conversation",
        message=Message(role=Role.ASSISTANT, content="你好，有什么可以帮你？"),
    )

    # 统一 recall
    conv = await mem.recall(memory_type="conversation", top_k=10)
    print("conversation:", [m.content for m in conv.messages or []])

    long_term = await mem.recall(query="简洁", mode="hybrid", top_k=5)
    print("long_term:", [i.content for i in long_term.items or []])

    print("handlers:", list(handlers.keys()))


if __name__ == "__main__":
    asyncio.run(main())
