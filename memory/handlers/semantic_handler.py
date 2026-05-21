from __future__ import annotations

from typing import Optional

from memory.embedders.base import Embedder
from memory.handlers.base import MemoryHandler
from memory.lifecycle import LifecyclePolicy, TTLBasedPolicy
from memory.models import SemanticItem
from memory.store.semantic_sqlite_store import SemanticSQLiteStore
from memory.utils import now_local_str


class SemanticHandler(MemoryHandler):
    """语义记忆专员：负责 semantic_memory 的写入/向量检索/删除/清空。"""

    def __init__(
        self,
        *,
        store: SemanticSQLiteStore,
        embedder: Embedder,
        namespace: str,
        lifecycle_policy: LifecyclePolicy | None = None,
    ):
        self.store = store
        self.embedder = embedder
        self.namespace = namespace
        self._lifecycle_policy = lifecycle_policy or TTLBasedPolicy(
            ttl_days=90, max_items=300
        )

    async def remember(
        self,
        *,
        content: str,
        source: str = "memory",
        metadata: Optional[dict] = None,
    ) -> str:
        emb = (await self.embedder.embed([content]))[0]
        item = SemanticItem(
            id=None,
            content=content,
            namespace=self.namespace,
            source=source,  # type: ignore[arg-type]
            metadata=metadata or {},
            created_at=now_local_str(),
            last_accessed_at=now_local_str(),
            embedding=emb,
        )
        return await self.store.add(item)

    async def recall(
        self,
        *,
        query: str,
        top_k: int = 3,
        filters: Optional[dict] = None,
        mode: str = "semantic",
    ) -> list[SemanticItem]:
        q_emb = (await self.embedder.embed([query]))[0]
        return await self.store.search(
            namespace=self.namespace,
            query_embedding=q_emb,
            top_k=top_k,
            filters=filters,
        )

    async def forget(self, item_id: str) -> bool:
        return await self.store.delete(item_id, self.namespace)

    async def clear_all(self) -> int:
        return await self.store.clear_namespace(self.namespace)

    async def run_maintenance(self, current_time_str: str) -> int:
        return await self._lifecycle_policy.evict(
            self.store, self.namespace, current_time_str
        )
