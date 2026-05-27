from __future__ import annotations

from typing import Optional

from memory.embedders.base import Embedder
from memory.handlers.base import MemoryHandler
from memory.lifecycle import LifecyclePolicy, TTLBasedPolicy
from memory.models import SemanticItem
from memory.store.qdrant_memory_store import QdrantMemoryStore
from memory.store.qdrant_scope import QdrantMemoryStoreScope
from memory.utils import now_local_str


class SemanticQdrantHandler(MemoryHandler):
    """语义记忆（Qdrant）：写入与检索均走向量。

    Args:
        store: 存储实例
        embedder: 嵌入器实例
        namespace: 命名空间
        lifecycle_policy: 生命周期策略
        score_threshold: 得分阈值，是向量检索的相似度下限，只有得分 ≥ 这个值 的结果才会返回，用来过滤「不太相关」的记忆。
    Actions:
        remember: 添加语义记忆
        recall: 检索语义记忆
        forget: 删除语义记忆
        clear_all: 清空命名空间
        run_maintenance: 执行生命周期维护
    """

    def __init__(
        self,
        *,
        store: QdrantMemoryStore,
        embedder: Embedder,
        namespace: str,
        lifecycle_policy: LifecyclePolicy | None = None,
        score_threshold: float | None = None,
    ) -> None:
        self.store = store
        self.embedder = embedder
        self.namespace = namespace
        self._score_threshold = score_threshold
        self._lifecycle_policy = lifecycle_policy or TTLBasedPolicy(
            ttl_days=90, max_items=300
        )
        self._scoped = QdrantMemoryStoreScope(store, "semantic")

    async def remember(
        self,
        *,
        content: str,
        source: str = "memory",
        metadata: Optional[dict] = None,
    ) -> str:
        emb = (await self.embedder.embed([content]))[0]
        meta = dict(metadata or {})
        ref_session_id = meta.pop("ref_session_id", None)
        importance = int(meta.pop("importance", 0) or 0)
        embedding_model = getattr(self.embedder, "model_name", None)
        item = SemanticItem(
            id=None,
            content=content,
            namespace=self.namespace,
            source=source,  # type: ignore[arg-type]
            metadata=meta,
            created_at=now_local_str(),
            last_accessed_at=now_local_str(),
            embedding=emb,
            ref_session_id=ref_session_id,
            embedding_model=embedding_model,
            embedding_dim=len(emb),
            importance=importance,
        )
        return await self.store.add_semantic(item)

    async def recall(
        self,
        *,
        query: str,
        top_k: int = 3,
        filters: Optional[dict] = None,
        mode: str = "semantic",
    ) -> list[SemanticItem]:
        _ = mode
        q_emb = (await self.embedder.embed([query]))[0]
        return await self.store.search_semantic(
            namespace=self.namespace,
            query_embedding=q_emb,
            top_k=top_k,
            score_threshold=self._score_threshold,
            filters=filters,
        )

    async def forget(self, item_id: str) -> bool:
        return await self.store.delete(item_id, self.namespace)

    async def clear_all(self) -> int:
        return await self.store.clear_namespace(self.namespace, memory_type="semantic")

    async def run_maintenance(self, current_time_str: str) -> int:
        return await self._lifecycle_policy.evict(
            self._scoped, self.namespace, current_time_str
        )
