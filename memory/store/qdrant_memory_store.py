"""Qdrant 向量存储：统一承载 episodic / semantic 长期记忆。

单 Collection + payload 字段 ``memory_type`` 区分类型；不替代 SQLite 版 Store，供新 Handler 使用。
"""

from __future__ import annotations

import os
from dotenv import load_dotenv

load_dotenv()
import uuid
from typing import Any, Literal, Optional

from qdrant_client import AsyncQdrantClient
from qdrant_client.models import (
    Distance,
    FieldCondition,
    Filter,
    MatchValue,
    PayloadSchemaType,
    PointStruct,
    VectorParams,
)

from memory.models import EpisodicItem, SemanticItem
from memory.types import LongTermMemoryType, MemorySource
from memory.utils import content_hash, now_local_str

# 默认相似度下限（cosine）；可按环境变量覆盖
_DEFAULT_SCORE_THRESHOLD = 0.55


class QdrantMemoryStore:
    """episodic + semantic 的 Qdrant 实现。

    Args:
        url: Qdrant 服务地址，默认环境变量 ``QDRANT_URL`` 或 ``http://localhost:6333``
        collection_name: 集合名，默认 ``QDRANT_COLLECTION`` 或 ``agentcortex_memory``
        api_key: 可选 API Key（Qdrant Cloud）
        distance: 距离度量，默认 COSINE
    Actions:
        add_episodic: 添加情景记忆
        add_semantic: 添加语义记忆
        search_episodic: 检索情景记忆
        search_semantic: 检索语义记忆
        delete: 删除记忆
        clear_namespace: 清空命名空间
        ttl_evict: 按 TTL 淘汰记忆
        capacity_evict: 按容量淘汰记忆
        close: 关闭连接
    """

    def __init__(
        self,
        *,
        url: str | None = None,
        collection_name: str | None = None,
        api_key: str | None = None,
        distance: Distance = Distance.COSINE,
    ) -> None:
        self.api_key = api_key or os.getenv("QDRANT_API_KEY")
        if not self.api_key:
            raise ValueError("QDRANT_API_KEY is required for QdrantMemoryStore")
        self.url = url or os.getenv("QDRANT_URL", "http://localhost:6333")
        self.collection_name = collection_name or os.getenv(
            "QDRANT_COLLECTION", "agentcortex_memory_v1024"
        )
        self._distance = distance
        self._client = AsyncQdrantClient(url=self.url, api_key=self.api_key)
        self._collection_ready: set[int] = set()
        self._payload_indexes_ready = False

    async def close(self) -> None:

        await self._client.close()

    # ── 写入 ─────────────────────────────────────────────

    async def add_episodic(self, item: EpisodicItem, embedding: list[float]) -> str:
        """写入情景记忆（向量由调用方 embed 后传入）。"""
        return await self._upsert(item, embedding, memory_type="episodic")

    async def add_semantic(self, item: SemanticItem) -> str:
        """写入语义记忆（使用 item.embedding）。"""
        if not item.embedding:
            raise ValueError("SemanticItem.embedding 不能为空")
        return await self._upsert(item, item.embedding, memory_type="semantic")

    async def _upsert(
        self,
        item: EpisodicItem | SemanticItem,
        embedding: list[float],
        memory_type: LongTermMemoryType,
    ) -> str:
        if not item.id:
            item.id = uuid.uuid4().hex
        if not item.content_hash:
            item.content_hash = content_hash(item.content)

        await self._ensure_collection(len(embedding))

        payload = self._item_to_payload(item, memory_type=memory_type)
        point = PointStruct(
            id=item.id,
            vector=embedding,
            payload=payload,
        )
        await self._client.upsert(
            collection_name=self.collection_name,
            points=[point],
        )
        return item.id

    # ── 检索 ─────────────────────────────────────────────

    async def search_episodic(
        self,
        *,
        namespace: str,
        query_embedding: list[float],
        top_k: int = 5,
        score_threshold: float | None = None,
        filters: Optional[dict] = None,
    ) -> list[EpisodicItem]:
        return await self._search(
            namespace=namespace,
            query_embedding=query_embedding,
            memory_type="episodic",
            top_k=top_k,
            score_threshold=score_threshold,
            filters=filters,
        )

    async def search_semantic(
        self,
        *,
        namespace: str,
        query_embedding: list[float],
        top_k: int = 5,
        score_threshold: float | None = None,
        filters: Optional[dict] = None,
    ) -> list[SemanticItem]:
        return await self._search(
            namespace=namespace,
            query_embedding=query_embedding,
            memory_type="semantic",
            top_k=top_k,
            score_threshold=score_threshold,
            filters=filters,
        )

    async def _search(
        self,
        *,
        namespace: str,
        query_embedding: list[float],
        memory_type: LongTermMemoryType,
        top_k: int,
        score_threshold: float | None,
        filters: Optional[dict],
    ) -> list[Any]:
        if not query_embedding:
            return []

        await self._ensure_collection(len(query_embedding))
        threshold = (
            _DEFAULT_SCORE_THRESHOLD if score_threshold is None else score_threshold
        )
        q_filter = self._build_filter(
            namespace=namespace,
            memory_type=memory_type,
            extra_filters=filters,
        )

        response = await self._client.query_points(
            collection_name=self.collection_name,
            query=query_embedding,
            query_filter=q_filter,
            limit=top_k,
            score_threshold=threshold,
            with_payload=True,
            with_vectors=True,
        )
        points = response.points or []

        now = now_local_str()
        items: list[Any] = []
        update_points: list[PointStruct] = []

        for ranked in points:
            payload = dict(ranked.payload or {})
            access_count = int(payload.get("access_count", 0)) + 1
            payload["last_accessed_at"] = now
            payload["access_count"] = access_count

            vector = ranked.vector
            if isinstance(vector, dict):
                vector = vector.get("") or next(iter(vector.values()), [])
            elif not isinstance(vector, list):
                vector = []

            if memory_type == "episodic":
                item = self._payload_to_episodic(str(ranked.id), payload)
            else:
                item = self._payload_to_semantic(str(ranked.id), payload, vector or [])
            item.metadata["score"] = float(ranked.score)
            items.append(item)

            update_points.append(
                PointStruct(id=ranked.id, vector=vector or [], payload=payload)
            )

        if update_points:
            await self._client.upsert(
                collection_name=self.collection_name,
                points=update_points,
            )

        return items

    # ── 删除 / 清空 ───────────────────────────────────────

    async def delete(self, item_id: str, namespace: str) -> bool:
        """按 id 删除；若 namespace 与 payload 不一致则拒绝删除。"""
        records = await self._client.retrieve(
            collection_name=self.collection_name,
            ids=[item_id],
            with_payload=True,
            with_vectors=False,
        )
        if not records:
            return False
        payload = records[0].payload or {}
        if payload.get("namespace") != namespace:
            return False
        await self._client.delete(
            collection_name=self.collection_name,
            points_selector=[item_id],
        )
        return True

    async def clear_namespace(
        self,
        namespace: str,
        memory_type: LongTermMemoryType | None = None,
    ) -> int:
        """清空某 namespace 下全部或指定 memory_type 的点；返回删除条数（约数）。"""
        q_filter = self._build_filter(namespace=namespace, memory_type=memory_type)
        points = await self._scroll_all(query_filter=q_filter)
        if not points:
            return 0
        ids = [p.id for p in points]
        await self._client.delete(
            collection_name=self.collection_name,
            points_selector=ids,
        )
        return len(ids)

    async def clear_collection(self) -> int:
        """删除当前 collection 内全部向量点（所有 namespace）；返回删除条数。"""
        all_points: list[Any] = []
        offset = None
        while True:
            records, offset = await self._client.scroll(
                collection_name=self.collection_name,
                limit=256,
                offset=offset,
                with_payload=False,
                with_vectors=False,
            )
            all_points.extend(records)
            if offset is None:
                break
        if not all_points:
            return 0
        ids = [p.id for p in all_points]
        batch_size = 256
        for i in range(0, len(ids), batch_size):
            batch = ids[i : i + batch_size]
            await self._client.delete(
                collection_name=self.collection_name,
                points_selector=batch,
            )
        return len(ids)

    # ── 生命周期（供 TTLBasedPolicy 调用）────────────────

    async def ttl_evict(
        self,
        namespace: str,
        threshold_str: str,
        memory_type: LongTermMemoryType | None = None,
    ) -> int:
        """删除 ``last_accessed_at`` 早于 ``threshold_str`` 的记忆（TEXT 时间比较）。"""
        q_filter = self._build_filter(namespace=namespace, memory_type=memory_type)
        points = await self._scroll_all(query_filter=q_filter)
        to_delete: list[str | int] = []
        for p in points:
            payload = p.payload or {}
            last_at = str(payload.get("last_accessed_at", ""))
            if last_at and last_at < threshold_str:
                to_delete.append(p.id)
        if not to_delete:
            return 0
        await self._client.delete(
            collection_name=self.collection_name,
            points_selector=to_delete,
        )
        return len(to_delete)

    async def capacity_evict(
        self,
        namespace: str,
        max_items: int,
        memory_type: LongTermMemoryType | None = None,
    ) -> int:
        """超过上限时按 importance↑、last_accessed↑、created_at↑ 淘汰（先删最不重要）。"""
        if max_items <= 0:
            return 0
        q_filter = self._build_filter(namespace=namespace, memory_type=memory_type)
        points = await self._scroll_all(query_filter=q_filter)
        if len(points) <= max_items:
            return 0
        overflow = len(points) - max_items

        def _sort_key(p: Any) -> tuple:
            pl = p.payload or {}
            return (
                int(pl.get("importance", 0)),
                str(pl.get("last_accessed_at", "")),
                int(pl.get("access_count", 0)),
                str(pl.get("created_at", "")),
            )

        points.sort(key=_sort_key)
        to_delete = [p.id for p in points[:overflow]]
        await self._client.delete(
            collection_name=self.collection_name,
            points_selector=to_delete,
        )
        return len(to_delete)

    # ── Collection 与 payload 工具 ───────────────────────

    async def _ensure_collection(self, vector_size: int) -> None:
        if vector_size in self._collection_ready:
            return
        exists = await self._client.collection_exists(self.collection_name)
        if not exists:
            await self._client.create_collection(
                collection_name=self.collection_name,
                vectors_config=VectorParams(
                    size=vector_size,
                    distance=self._distance,
                ),
            )
        else:
            info = await self._client.get_collection(self.collection_name)
            current_size = info.config.params.vectors.size  # type: ignore[union-attr]
            if current_size != vector_size:
                raise ValueError(
                    f"Qdrant 集合 {self.collection_name} 向量维度为 {current_size}，"
                    f"当前 embedding 维度为 {vector_size}，请换集合或统一 embedding 模型"
                )
        await self._ensure_payload_indexes()
        self._collection_ready.add(vector_size)

    async def _ensure_payload_indexes(self) -> None:
        """Qdrant Cloud 对带 filter 的查询要求 keyword 索引。"""
        if self._payload_indexes_ready:
            return
        for field in ("namespace", "memory_type"):
            await self._client.create_payload_index(
                collection_name=self.collection_name,
                field_name=field,
                field_schema=PayloadSchemaType.KEYWORD,
            )
        self._payload_indexes_ready = True

    async def _scroll_all(self, query_filter: Filter) -> list[Any]:
        """滚动拉取匹配 filter 的全部点（用于清空/淘汰）。"""
        all_points: list[Any] = []
        offset = None
        while True:
            records, offset = await self._client.scroll(
                collection_name=self.collection_name,
                scroll_filter=query_filter,
                limit=256,
                offset=offset,
                with_payload=True,
                with_vectors=False,
            )
            all_points.extend(records)
            if offset is None:
                break
        return all_points

    @staticmethod
    def _build_filter(
        *,
        namespace: str,
        memory_type: LongTermMemoryType | None = None,
        extra_filters: Optional[dict] = None,
    ) -> Filter:
        must: list[FieldCondition] = [
            FieldCondition(
                key="namespace",
                match=MatchValue(value=namespace),
            )
        ]
        if memory_type is not None:
            must.append(
                FieldCondition(
                    key="memory_type",
                    match=MatchValue(value=memory_type),
                )
            )
        if extra_filters:
            if "source" in extra_filters:
                must.append(
                    FieldCondition(
                        key="source",
                        match=MatchValue(value=extra_filters["source"]),
                    )
                )
            if "ref_session_id" in extra_filters:
                must.append(
                    FieldCondition(
                        key="ref_session_id",
                        match=MatchValue(value=extra_filters["ref_session_id"]),
                    )
                )
            if "embedding_model" in extra_filters:
                must.append(
                    FieldCondition(
                        key="embedding_model",
                        match=MatchValue(value=extra_filters["embedding_model"]),
                    )
                )
        return Filter(must=must)

    @staticmethod
    def _item_to_payload(
        item: EpisodicItem | SemanticItem,
        memory_type: LongTermMemoryType,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "memory_type": memory_type,
            "namespace": item.namespace,
            "content": item.content,
            "source": item.source,
            "metadata": item.metadata,
            "created_at": item.created_at,
            "last_accessed_at": item.last_accessed_at,
            "access_count": item.access_count,
            "ref_session_id": item.ref_session_id,
            "content_hash": item.content_hash,
            "importance": item.importance,
        }
        if isinstance(item, SemanticItem):
            payload["embedding_model"] = item.embedding_model
            payload["embedding_dim"] = item.embedding_dim
        return payload

    @staticmethod
    def _payload_to_episodic(point_id: str, payload: dict[str, Any]) -> EpisodicItem:
        return EpisodicItem(
            id=point_id,
            content=str(payload.get("content", "")),
            namespace=str(payload.get("namespace", "")),
            source=payload.get("source", "memory"),  # type: ignore[arg-type]
            metadata=payload.get("metadata") or {},
            created_at=str(payload.get("created_at", "")),
            last_accessed_at=str(payload.get("last_accessed_at", "")),
            access_count=int(payload.get("access_count", 0)),
            ref_session_id=payload.get("ref_session_id"),
            content_hash=payload.get("content_hash"),
            importance=int(payload.get("importance", 0)),
        )

    @staticmethod
    def _payload_to_semantic(
        point_id: str,
        payload: dict[str, Any],
        vector: list[float],
    ) -> SemanticItem:
        emb_dim = payload.get("embedding_dim")
        if emb_dim is None and vector:
            emb_dim = len(vector)
        return SemanticItem(
            id=point_id,
            content=str(payload.get("content", "")),
            namespace=str(payload.get("namespace", "")),
            source=payload.get("source", "memory"),  # type: ignore[arg-type]
            metadata=payload.get("metadata") or {},
            created_at=str(payload.get("created_at", "")),
            last_accessed_at=str(payload.get("last_accessed_at", "")),
            access_count=int(payload.get("access_count", 0)),
            embedding=list(vector),
            ref_session_id=payload.get("ref_session_id"),
            content_hash=payload.get("content_hash"),
            embedding_model=payload.get("embedding_model"),
            embedding_dim=int(emb_dim) if emb_dim is not None else None,
            importance=int(payload.get("importance", 0)),
        )


if __name__ == "__main__":
    import asyncio

    async def _smoke() -> None:
        """本地/云端 Qdrant 连通性与 Store 方法冒烟测试。运行：
        ``uv run python -m memory.store.qdrant_memory_store``
        """
        ns = "mem:store_smoke:test"
        dim = 1024
        emb = [0.1] * dim
        emb_alt = [0.11] * dim  # 略不同，用于 semantic 第二条

        store = QdrantMemoryStore()
        print("url:", store.url, "collection:", store.collection_name)

        exists_before = await store._client.collection_exists(store.collection_name)
        print("[1] collection_exists (before write):", exists_before)

        # ── add_episodic + search_episodic ──
        ep = EpisodicItem(
            content="用户偏好简洁回复哈哈哈哈哈哈我是测试情景记忆",
            namespace=ns,
            importance=10,
        )
        ep_id = await store.add_episodic(ep, emb)
        print("[2] add_episodic id:", ep_id)

        ep_hits = await store.search_episodic(
            namespace=ns,
            query_embedding=emb,
            top_k=3,
            score_threshold=0.5,
        )
        print(
            "[3] search_episodic:",
            [(h.id, h.content[:12], h.access_count) for h in ep_hits],
        )

        # ── add_semantic + search_semantic ──
        sem = SemanticItem(
            content="偏好简洁、少废话我是测试语义记忆",
            namespace=ns,
            embedding=emb_alt,
            importance=20,
        )
        sem_id = await store.add_semantic(sem)
        print("[4] add_semantic id:", sem_id)

        sem_hits = await store.search_semantic(
            namespace=ns,
            query_embedding=emb_alt,
            top_k=3,
            score_threshold=0.5,
        )
        print(
            "[5] search_semantic:",
            [(h.id, h.content[:12], len(h.embedding or [])) for h in sem_hits],
        )

        # ── delete ──
        # deleted = await store.delete(ep_id, ns)
        # print("[6] delete episodic:", deleted)
        # ep_after = await store.search_episodic(
        #     namespace=ns, query_embedding=emb, top_k=5, score_threshold=0.3
        # )
        # print("[7] search after delete (episodic count):", len(ep_after))

        # # ── ttl_evict：写入一条“很久未访问”的 semantic ──
        # from memory.utils import subtract_days_local_str

        # old_ts = subtract_days_local_str(now_local_str(), 60)
        # stale = SemanticItem(
        #     content="过期测试条目",
        #     namespace=ns,
        #     embedding=emb,
        #     last_accessed_at=old_ts,
        #     created_at=old_ts,
        # )
        # stale_id = await store.add_semantic(stale)
        # ttl_removed = await store.ttl_evict(
        #     ns, subtract_days_local_str(now_local_str(), 30), memory_type="semantic"
        # )
        # print("[8] ttl_evict removed:", ttl_removed, "stale_id:", stale_id)

        # # ── capacity_evict：同一 namespace 再塞几条 episodic ──
        # for i in range(4):
        #     await store.add_episodic(
        #         EpisodicItem(content=f"容量测试-{i}", namespace=ns, importance=i),
        #         emb,
        #     )
        # cap_removed = await store.capacity_evict(
        #     ns, max_items=2, memory_type="episodic"
        # )
        # print("[9] capacity_evict removed:", cap_removed)

        # # ── clear_namespace ──
        # cleared = await store.clear_namespace(ns)
        # print("[10] clear_namespace removed:", cleared)

        # exists_after = await store._client.collection_exists(store.collection_name)
        # print("[11] collection_exists (after tests):", exists_after)
        await store.close()
        print("done.")

    asyncio.run(_smoke())
