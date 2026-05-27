from __future__ import annotations

from typing import Optional

from memory.handlers.base import MemoryHandler
from memory.models import AssociativeRecallResult, GraphEntity
from memory.store import Neo4jStore
from memory.types import EntityType, LongTermMemoryType, MemorySource
from memory.utils import now_local_str


class AssociativeHandler(MemoryHandler):
    """联想记忆专员：实体与关系写入 Neo4j，按图邻域检索。

    与 episodic/semantic 不同，除统一 ``remember`` 外提供图语义专用方法。

    ``remember`` 约定（通过 ``metadata``）：

    - **建关系**：``from_name`` + ``to_name``（可选 ``relation_label``、``from_entity_type``、``to_entity_type``、``weight``）
    - **建/更新实体**：``entity_name``（可选 ``entity_type``、``aliases``、``description``）；未传时用 ``content`` 作实体名
    - **挂接向量记忆**：``entity_id`` + ``memory_type`` + ``memory_id``（可选 ``content_preview``）

    Args:
        store: Neo4jStore 实例
        namespace: 命名空间
        default_hops: 默认邻域跳数
        include_memory_refs_on_recall: 是否在召回时包含 MemoryRef

    Actions:
        remember_relation: 建立两实体及 ``RELATES_TO`` 关系
        remember_entity: 合并单个实体节点
        link_memory: 实体挂载 ``MemoryRef``，指向 Qdrant episodic/semantic
        recall_graph: 图检索完整结果（种子实体 + 邻域 + 关系 + 可选 MemoryRef）
        recall: 返回种子实体 + 邻域实体列表（供日后 Manager 拼装）
        forget: 删除实体节点（``DETACH DELETE``，含关联边）
        clear_all: 删除该命名空间下全部 Entity 与 MemoryRef 节点
        run_maintenance: 执行生命周期维护（TTL / 容量等），返回本 handler 删除的总条数

    """

    def __init__(
        self,
        *,
        store: Neo4jStore,
        namespace: str,
        default_hops: int = 1,
        include_memory_refs_on_recall: bool = True,
    ) -> None:
        self.store = store
        self.namespace = namespace
        self.default_hops = default_hops
        self._include_memory_refs = include_memory_refs_on_recall

    # ── 图语义专用 API ───────────────────────────────────

    async def remember_relation(
        self,
        *,
        from_name: str,
        to_name: str,
        relation_label: str | None = None,
        from_entity_type: EntityType = "other",
        to_entity_type: EntityType = "other",
        weight: float = 1.0,
    ) -> str:
        """建立两实体及 ``RELATES_TO`` 关系，返回关系 elementId。"""
        return await self.store.relate(
            namespace=self.namespace,
            from_name=from_name,
            to_name=to_name,
            relation_label=relation_label,
            from_entity_type=from_entity_type,
            to_entity_type=to_entity_type,
            weight=weight,
        )

    async def remember_entity(
        self,
        *,
        name: str,
        entity_type: EntityType = "other",
        description: str | None = None,
        aliases: list[str] | None = None,
        source: MemorySource = "memory",
        metadata: Optional[dict] = None,
        ref_session_id: str | None = None,
        importance: int = 0,
    ) -> str:
        """合并单个实体节点，返回 entity id。"""
        entity = GraphEntity(
            id=None,
            namespace=self.namespace,
            name=name,
            entity_type=entity_type,
            aliases=list(aliases or []),
            description=description,
            metadata=dict(metadata or {}),
            source=source,
            ref_session_id=ref_session_id,
            importance=importance,
            created_at=now_local_str(),
        )
        return await self.store.upsert_entity(entity)

    async def link_memory(
        self,
        *,
        entity_id: str,
        memory_type: LongTermMemoryType,
        memory_id: str,
        content_preview: str | None = None,
    ) -> str:
        """实体挂载 ``MemoryRef``，指向 Qdrant episodic/semantic。"""
        return await self.store.link_memory(
            namespace=self.namespace,
            entity_id=entity_id,
            memory_type=memory_type,
            memory_id=memory_id,
            content_preview=content_preview,
        )

    async def recall_graph(
        self,
        *,
        query: str,
        top_k: int = 10,
        filters: Optional[dict] = None,
    ) -> AssociativeRecallResult:
        """图检索完整结果（种子实体 + 邻域 + 关系 + 可选 MemoryRef）。"""
        meta = dict(filters or {})
        hops = int(meta.get("hops", self.default_hops))
        include_refs = bool(meta.get("include_memory_refs", self._include_memory_refs))
        return await self.store.recall_neighbors(
            namespace=self.namespace,
            query=query,
            hops=hops,
            limit=top_k,
            include_memory_refs=include_refs,
        )

    # ── MemoryHandler 统一接口 ───────────────────────────

    async def remember(
        self,
        *,
        content: str,
        source: str = "memory",
        metadata: Optional[dict] = None,
    ) -> str:
        meta = dict(metadata or {})
        ref_session_id = meta.pop("ref_session_id", None)
        importance = int(meta.pop("importance", 0) or 0)

        if meta.get("entity_id") and meta.get("memory_type") and meta.get("memory_id"):
            return await self.link_memory(
                entity_id=str(meta["entity_id"]),
                memory_type=meta["memory_type"],  # type: ignore[arg-type]
                memory_id=str(meta["memory_id"]),
                content_preview=meta.get("content_preview"),
            )

        from_name = meta.pop("from_name", None)
        to_name = meta.pop("to_name", None)
        if from_name and to_name:
            return await self.remember_relation(
                from_name=str(from_name),
                to_name=str(to_name),
                relation_label=meta.pop("relation_label", content or None),
                from_entity_type=meta.pop("from_entity_type", "other"),  # type: ignore[arg-type]
                to_entity_type=meta.pop("to_entity_type", "other"),  # type: ignore[arg-type]
                weight=float(meta.pop("weight", 1.0) or 1.0),
            )

        entity_name = meta.pop("entity_name", None) or (
            content.strip() if content else None
        )
        if not entity_name:
            raise ValueError(
                "associative remember 需要 metadata.from_name+to_name、"
                "metadata.entity_id+memory_*、或 content/entity_name 作为实体名"
            )
        return await self.remember_entity(
            name=str(entity_name),
            entity_type=meta.pop("entity_type", "other"),  # type: ignore[arg-type]
            description=meta.pop("description", None),
            aliases=meta.pop("aliases", None),
            source=source,  # type: ignore[arg-type]
            metadata=meta,
            ref_session_id=ref_session_id,
            importance=importance,
        )

    async def recall(
        self,
        *,
        query: str,
        top_k: int = 10,
        filters: Optional[dict] = None,
        mode: str = "graph",
    ) -> list[GraphEntity]:
        """返回种子实体 + 邻域实体列表（供日后 Manager 拼装）。"""
        _ = mode
        result = await self.recall_graph(query=query, top_k=top_k, filters=filters)
        items: list[GraphEntity] = []
        if result.seed is not None:
            items.append(result.seed)
        for entity in result.entities:
            if result.seed and entity.id == result.seed.id:
                continue
            items.append(entity)
            if len(items) >= top_k:
                break
        return items[:top_k]

    async def forget(self, item_id: str) -> bool:
        """删除实体节点（``DETACH DELETE``，含关联边）。"""
        return await self.store.delete_entity(item_id, self.namespace)

    async def clear_all(self) -> int:
        return await self.store.clear_namespace(self.namespace)

    async def run_maintenance(self, current_time_str: str) -> int:
        _ = current_time_str
        return 0
