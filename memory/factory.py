"""MemoryManager 组装工厂。"""

from __future__ import annotations

from pathlib import Path
from typing import Literal

from memory.embedders import OpenAIEmbedder
from memory.embedders.base import Embedder
from memory.handlers import (
    AssociativeHandler,
    ConversationHandler,
    EpisodicHandler,
    EpisodicQdrantHandler,
    MemoryHandler,
    SemanticHandler,
    SemanticQdrantHandler,
)
from memory.manager import MemoryManager
from memory.store.conversation_sqlite_store import ConversationSQLitesStore
from memory.store.episodic_sqlite_store import EpisodicSQLiteStore
from memory.store.neo4j_store import Neo4jStore
from memory.store.qdrant_memory_store import QdrantMemoryStore
from memory.store.semantic_sqlite_store import SemanticSQLiteStore

VectorBackend = Literal["sqlite", "qdrant"]
GraphBackend = Literal["neo4j", "none"]


def create_memory_manager(
    *,
    namespace: str,
    db_path: str = "data/memory.db",
    vector_backend: VectorBackend = "qdrant",
    qdrant_url: str | None = None,
    qdrant_collection: str | None = None,
    embedder: Embedder | None = None,
    graph_backend: GraphBackend = "neo4j",
    neo4j_uri: str | None = None,
) -> MemoryManager:
    """创建带 conversation + 长期记忆 + 联想记忆的 MemoryManager。

    Args:
        namespace: 长期记忆命名空间；conversation 使用同一字符串作为 session_id
        db_path: SQLite 路径（conversation 必选；sqlite 向量后端时 episodic/semantic 也用）
        vector_backend: ``qdrant`` 使用 Qdrant 向量库；``sqlite`` 保留旧 SQLite 实现
        qdrant_url: Qdrant 地址，默认读环境变量 ``QDRANT_URL``
        qdrant_collection: 集合名，默认读 ``QDRANT_COLLECTION``
        embedder: 向量嵌入器，默认 ``OpenAIEmbedder()``
        graph_backend: ``neo4j`` 注册 associative；``none`` 不启用图记忆
        neo4j_uri: Neo4j 地址，默认读 ``NEO4J_URI``
    """
    Path(db_path).parent.mkdir(parents=True, exist_ok=True)

    conversation_store = ConversationSQLitesStore(db_path)
    handlers: dict[str, MemoryHandler] = {
        "conversation": ConversationHandler(
            store=conversation_store,
            session_id=namespace,
        ),
    }

    if vector_backend == "qdrant":
        emb = embedder or OpenAIEmbedder()
        qdrant_store = QdrantMemoryStore(
            url=qdrant_url,
            collection_name=qdrant_collection,
        )
        handlers["episodic"] = EpisodicQdrantHandler(
            store=qdrant_store,
            embedder=emb,
            namespace=namespace,
        )
        handlers["semantic"] = SemanticQdrantHandler(
            store=qdrant_store,
            embedder=emb,
            namespace=namespace,
        )
    else:
        handlers["episodic"] = EpisodicHandler(
            store=EpisodicSQLiteStore(db_path),
            namespace=namespace,
        )
        handlers["semantic"] = SemanticHandler(
            store=SemanticSQLiteStore(db_path),
            embedder=embedder or OpenAIEmbedder(),
            namespace=namespace,
        )

    if graph_backend == "neo4j":
        neo4j_store = Neo4jStore(uri=neo4j_uri)
        handlers["associative"] = AssociativeHandler(
            store=neo4j_store,
            namespace=namespace,
        )

    return MemoryManager(handlers=handlers)
