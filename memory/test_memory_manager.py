"""本地验证：实例化 Store 时会建库、建表。运行：uv run python -m memory.test_memory_manager"""

from __future__ import annotations

import asyncio
from pathlib import Path

from memory.models import EpisodicItem
from memory.store.episodic_sqlite_store import EpisodicSQLiteStore
from memory.store.semantic_sqlite_store import SemanticSQLiteStore
from memory.store.conversation_sqlite_store import ConversationSQLitesStore

# from memory.handlers import MemoryHandler, EpisodicHandler, SemanticHandler
# from memory.embedders import OpenAIEmbedder


async def main() -> None:
    db_path = "data/memory_test.db"
    namespace = "mem:tester:default"

    # SQLite 不会自动创建父目录，需先确保 data/ 存在
    Path(db_path).parent.mkdir(parents=True, exist_ok=True)

    episodic_store = EpisodicSQLiteStore(db_path)
    semantic_store = SemanticSQLiteStore(db_path)
    conversation_store = ConversationSQLitesStore(db_path)

    print(f"已建表: episodic_memory, semantic_memory, conversation_memory")
    # handlers: dict[str, MemoryHandler] = {
    #     "episodic": EpisodicHandler(store=episodic_store, namespace=namespace),
    #     "semantic": SemanticHandler(
    #         store=semantic_store,
    #         embedder=OpenAIEmbedder(),
    #         namespace=namespace,
    #     ),
    # }


if __name__ == "__main__":
    asyncio.run(main())
