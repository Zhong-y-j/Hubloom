"""MemoryManager 组装工厂。"""

from __future__ import annotations

from typing import Literal

from embedders import OpenAIEmbedder
from embedders.base import Embedder
from memory.handlers import (
    AssociativeHandler,
    ConversationHandler,
    EpisodicQdrantHandler,
    MemoryHandler,
    SemanticQdrantHandler,
)
from memory.manager import MemoryManager
from memory.store import (
    ConversationStore,
    Neo4jStore,
    QdrantMemoryStore,
    create_conversation_store,
)

VectorBackend = Literal["sqlite", "qdrant", "none"]
GraphBackend = Literal["neo4j", "none"]


def create_memory_manager(
    *,
    namespace: str,
    db_path: str = "data/memory.db",
    conversation_store: ConversationStore | None = None,
    conversation_backend: str | None = "sqlite",
    conversation_postgres_dsn: str | None = None,
    vector_backend: VectorBackend = "qdrant",
    qdrant_url: str | None = None,
    qdrant_collection: str | None = None,
    qdrant_api_key: str | None = None,
    embedder: Embedder | None = None,
    embedder_api_key: str | None = None,
    embedder_base_url: str | None = None,
    embedder_model: str | None = None,
    graph_backend: GraphBackend = "neo4j",
    neo4j_uri: str | None = None,
    neo4j_user: str | None = None,
    neo4j_password: str | None = None,
    neo4j_database: str | None = None,
    neo4j_skip_dns_check: bool | None = None,
) -> MemoryManager:
    """创建 MemoryManager（conversation 必选；长期记忆按 backend 可选）。

    长期后端参数由调用方（HubloomConfig）显式传入，不读环境变量。
    会话历史：``conversation_store`` 优先；否则按 ``conversation_backend`` 创建。
    """
    if conversation_store is None:
        conversation_store = create_conversation_store(
            backend=conversation_backend,
            db_path=db_path,
            postgres_dsn=conversation_postgres_dsn,
        )
    handlers: dict[str, MemoryHandler] = {
        "conversation": ConversationHandler(
            store=conversation_store,
            session_id=namespace,
        ),
    }

    if vector_backend == "qdrant":
        emb = embedder or OpenAIEmbedder(
            api_key=embedder_api_key,
            base_url=embedder_base_url,
            model=embedder_model,
        )
        qdrant_store = QdrantMemoryStore(
            url=qdrant_url,
            collection_name=qdrant_collection,
            api_key=qdrant_api_key,
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

    if graph_backend == "neo4j":
        neo4j_store = Neo4jStore(
            uri=neo4j_uri,
            user=neo4j_user,
            password=neo4j_password,
            database=neo4j_database,
            skip_dns_check=neo4j_skip_dns_check,
        )
        handlers["associative"] = AssociativeHandler(
            store=neo4j_store,
            namespace=namespace,
        )

    return MemoryManager(handlers=handlers)
