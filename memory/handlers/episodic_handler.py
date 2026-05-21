from __future__ import annotations

from typing import Optional

from memory.handlers.base import MemoryHandler
from memory.lifecycle import LifecyclePolicy, TTLBasedPolicy
from memory.models import EpisodicItem
from memory.store.episodic_sqlite_store import EpisodicSQLiteStore
from memory.utils import now_local_str


class EpisodicHandler(MemoryHandler):
    """情节记忆专员：负责 episodic_memory 的写入/关键词检索/删除/清空。"""

    def __init__(
        self,
        *,
        store: EpisodicSQLiteStore,
        namespace: str,
        lifecycle_policy: LifecyclePolicy | None = None,
    ):
        self.store = store
        self.namespace = namespace
        self._lifecycle_policy = lifecycle_policy or TTLBasedPolicy(
            ttl_days=30, max_items=1000
        )

    async def remember(
        self,
        *,
        content: str,
        source: str = "memory",
        metadata: Optional[dict] = None,
    ) -> str:
        item = EpisodicItem(
            id=None,
            content=content,
            namespace=self.namespace,
            source=source,  # type: ignore[arg-type]
            metadata=metadata or {},
            created_at=now_local_str(),
            last_accessed_at=now_local_str(),
        )
        return await self.store.add(item)

    async def recall(
        self,
        *,
        query: str,
        top_k: int = 3,
        filters: Optional[dict] = None,
        mode: str = "keyword",
    ) -> list[EpisodicItem]:
        # episodic 目前只支持 keyword 检索；mode 仅为统一接口保留
        return await self.store.search(
            namespace=self.namespace,
            query=query,
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
