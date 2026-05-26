from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Protocol, runtime_checkable

from memory.utils import subtract_days_local_str


@runtime_checkable
class SupportsLifecycleEvict(Protocol):
    """具备 TTL / 容量驱逐能力的存储（duck typing）。"""

    async def ttl_evict(self, namespace: str, threshold_str: str) -> int:
        """驱逐过期条目。

        Args:
            namespace: 命名空间
            threshold_str: 过期时间阈值

        Returns:
            删除的总条数
        """
        ...

    async def capacity_evict(self, namespace: str, max_items: int) -> int:
        """驱逐超额条目。

        Args:
            namespace: 命名空间
            max_items: 最大条数

        Returns:
            删除的总条数
        """
        ...


class LifecyclePolicy(ABC):
    """按命名空间对存储做维护（驱逐过期或超额条目）。"""

    @abstractmethod
    async def evict(
        self,
        store: SupportsLifecycleEvict,
        namespace: str,
        current_time_str: str,
    ) -> int:
        """返回本次删除的总行数。"""
        ...


class TTLBasedPolicy(LifecyclePolicy):
    """基于「最近访问时间」的 TTL + 单 namespace 最大条数。

    Args:
        ttl_days: 过期时间（天）
        max_items: 最大条数
    actions:
        - evict: 驱逐过期或超额条目
    """

    def __init__(self, ttl_days: int = 30, max_items: int = 1000) -> None:
        self.ttl_days = ttl_days
        self.max_items = max_items

    async def evict(
        self,
        store: SupportsLifecycleEvict,
        namespace: str,
        current_time_str: str,
    ) -> int:
        """驱逐过期或超额条目。

        Args:
            store: 存储器
            namespace: 命名空间
            current_time_str: 当前时间

        Returns:
            删除的总条数
        """
        removed = 0
        if self.ttl_days > 0:
            threshold_str = subtract_days_local_str(current_time_str, self.ttl_days)
            removed += await store.ttl_evict(namespace, threshold_str)
        if self.max_items > 0:
            removed += await store.capacity_evict(namespace, self.max_items)
        return removed
