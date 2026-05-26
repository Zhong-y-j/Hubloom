from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Optional


class MemoryHandler(ABC):
    """记忆处理器抽象基类：封装某一类记忆的存取与管理。"""

    @abstractmethod
    async def remember(
        self,
        *,
        content: str,
        source: str = "memory",
        metadata: Optional[dict] = None,
    ) -> str:
        raise NotImplementedError

    @abstractmethod
    async def recall(
        self,
        *,
        query: str,
        top_k: int = 3,
        filters: Optional[dict] = None,
        mode: str = "keyword",
    ) -> list:
        raise NotImplementedError

    @abstractmethod
    async def forget(self, item_id: str) -> bool:
        raise NotImplementedError

    @abstractmethod
    async def clear_all(self) -> int:
        raise NotImplementedError

    @abstractmethod
    async def run_maintenance(self, current_time_str: str) -> int:
        """执行生命周期维护（TTL / 容量等），返回本 handler 删除的总条数。"""
        raise NotImplementedError
