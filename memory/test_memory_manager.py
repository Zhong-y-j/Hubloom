"""本地验证：实例化 Store 时会建库、建表。运行：uv run python -m memory.test_memory_manager"""

from __future__ import annotations

import asyncio
from pathlib import Path

from core.models import Message, Role
from memory.store.conversation_sqlite_store import ConversationSQLitesStore
from memory.store.episodic_sqlite_store import EpisodicSQLiteStore
from memory.store.semantic_sqlite_store import SemanticSQLiteStore
from memory.store.conversation_sqlite_store import ConversationSQLitesStore

from memory.handlers import (
    MemoryHandler,
    EpisodicHandler,
    SemanticHandler,
    ConversationHandler,
)
from memory.embedders import OpenAIEmbedder


async def main() -> None:
    db_path = "data/memory_test.db"
    session_id = "sess_demo_001"
    namespace = f"mem:{session_id}:default"

    Path(db_path).parent.mkdir(parents=True, exist_ok=True)

    episodic_store = EpisodicSQLiteStore(db_path)
    semantic_store = SemanticSQLiteStore(db_path)
    conversation_store = ConversationSQLitesStore(db_path)

    print(f"已建表: episodic_memory, semantic_memory, conversation_memory")
    handlers: dict[str, MemoryHandler] = {
        "episodic": EpisodicHandler(store=episodic_store, namespace=namespace),
        "semantic": SemanticHandler(
            store=semantic_store,
            embedder=OpenAIEmbedder(),
            namespace=namespace,
        ),
        "conversation": ConversationHandler(
            store=conversation_store, session_id=session_id
        ),
    }

    await handlers["episodic"].remember(content="用户打招呼", metadata={"turn": 1})
    await handlers["semantic"].remember(content="用户打招呼", metadata={"turn": 1})
    await handlers["conversation"].append(Message(role=Role.USER, content="你好"))
    await handlers["conversation"].append(
        Message(role=Role.ASSISTANT, content="你好，有什么可以帮你？")
    )


if __name__ == "__main__":
    asyncio.run(main())
