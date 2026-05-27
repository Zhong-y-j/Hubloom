from __future__ import annotations

from typing import Optional

from observability import log, logger
from embedders.base import Embedder
from memory.handlers.base import MemoryHandler
from memory.lifecycle import LifecyclePolicy, TTLBasedPolicy
from memory.models import SemanticItem
from memory.store.qdrant_memory_store import QdrantMemoryStore
from memory.store.qdrant_scope import QdrantMemoryStoreScope
from memory.utils import now_local_str


def _preview(text: str, limit: int = 80) -> str:
    text = (text or "").replace("\n", " ")
    return text if len(text) <= limit else text[:limit] + "…"


def _hits_preview(items: list[SemanticItem], limit: int = 3) -> str:
    parts: list[str] = []
    for it in (items or [])[: max(0, limit)]:
        score = it.metadata.get("score")
        try:
            score_s = f"{float(score):.3f}"
        except Exception:
            score_s = "?"
        parts.append(f"{score_s}:{_preview(it.content, 60)}")
    return "; ".join(parts)


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
        try:
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
            item_id = await self.store.add_semantic(item)
        except Exception as e:
            logger.warning(
                "semantic remember failed | namespace={} | detail={}",
                self.namespace,
                str(e)[:200],
            )
            raise
        log(
            "semantic remember",
            namespace=self.namespace,
            id=item_id,
            importance=importance,
            preview=_preview(content),
        )
        return item_id

    async def recall(
        self,
        *,
        query: str,
        top_k: int = 3,
        filters: Optional[dict] = None,
        mode: str = "semantic",
    ) -> list[SemanticItem]:
        _ = mode
        try:
            q_emb = (await self.embedder.embed([query]))[0]
            items = await self.store.search_semantic(
                namespace=self.namespace,
                query_embedding=q_emb,
                top_k=top_k,
                score_threshold=self._score_threshold,
                filters=filters,
            )
        except Exception as e:
            logger.warning(
                "semantic recall failed | namespace={} | detail={}",
                self.namespace,
                str(e)[:200],
            )
            raise
        log(
            "semantic recall",
            namespace=self.namespace,
            query=_preview(query),
            count=len(items),
            top_k=top_k,
            hits=_hits_preview(items),
        )
        return items

    async def forget(self, item_id: str) -> bool:
        try:
            ok = await self.store.delete(item_id, self.namespace)
        except Exception as e:
            logger.warning(
                "semantic forget failed | namespace={} | id={} | detail={}",
                self.namespace,
                item_id,
                str(e)[:200],
            )
            raise
        log("semantic forget", namespace=self.namespace, id=item_id, ok=ok)
        return ok

    async def clear_all(self) -> int:
        try:
            n = await self.store.clear_namespace(self.namespace, memory_type="semantic")
        except Exception as e:
            logger.warning(
                "semantic clear failed | namespace={} | detail={}",
                self.namespace,
                str(e)[:200],
            )
            raise
        log("semantic clear", namespace=self.namespace, deleted=n)
        return n

    async def run_maintenance(self, current_time_str: str) -> int:
        try:
            n = await self._lifecycle_policy.evict(
                self._scoped, self.namespace, current_time_str
            )
        except Exception as e:
            logger.warning(
                "semantic maintenance failed | namespace={} | detail={}",
                self.namespace,
                str(e)[:200],
            )
            raise
        if n:
            log("semantic maintenance", namespace=self.namespace, evicted=n)
        return n
