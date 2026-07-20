"""将 QdrantMemoryStore 限定到单一 memory_type，供 LifecyclePolicy 使用。"""

from __future__ import annotations

from memory.store.qdrant_memory_store import QdrantMemoryStore
from memory.types import LongTermMemoryType


class QdrantMemoryStoreScope:
    """实现 ``SupportsLifecycleEvict``，仅对一种长期记忆类型做 TTL/容量驱逐。"""

    def __init__(
        self,
        store: QdrantMemoryStore,
        memory_type: LongTermMemoryType,
    ) -> None:
        self._store = store
        self._memory_type = memory_type

    async def ttl_evict(self, namespace: str, threshold_str: str) -> int:
        return await self._store.ttl_evict(
            namespace, threshold_str, memory_type=self._memory_type
        )

    async def capacity_evict(self, namespace: str, max_items: int) -> int:
        return await self._store.capacity_evict(
            namespace, max_items, memory_type=self._memory_type
        )
