from abc import ABC, abstractmethod
from typing import Optional
from ..models import EpisodicItem, SemanticItem


class BaseStore(ABC):
    """记忆存储后端抽象接口

    所有存储实现（SQLite、Chroma 等）必须实现此接口。
    Agent 范式层绝不可直接依赖具体实现，只能通过此接口访问。
    """

    @abstractmethod
    async def add(self, item: EpisodicItem) -> str:
        """添加一条记忆，返回记忆 ID。

        约定：
        - 若 `item.id is None`，实现方应生成一个新 ID（例如 UUID）并持久化。
        - 若 `item.id` 已存在，实现方可选择 upsert 或报错；建议在具体实现里明确策略。

        Args:
            item: 记忆条目
        Returns:
            记忆 ID
        """
        ...

    async def add_semantic(self, item: SemanticItem) -> str:
        """添加一条语义记忆（可选接口）。

        默认实现为“不支持”。具体 store（SQLite/向量库）可覆盖此方法。
        """
        raise NotImplementedError("Semantic memory is not supported by this store")

    @abstractmethod
    async def search(
        self,
        namespace: str,
        query: str,
        top_k: int = 5,
        filters: Optional[dict] = None,
    ) -> list[EpisodicItem]:
        """
        检索记忆（强制隔离）。

        Args:
            namespace: 命名空间（必填，无默认值，强制调用方指定隔离域）
            query: 查询文本
            top_k: 返回条数
            filters: 额外过滤条件
        Returns:
            匹配的记忆列表（实现方应在命中时更新 last_accessed_at 和 access_count）
        """
        ...

    async def search_semantic(
        self,
        *,
        namespace: str,
        query_embedding: list[float],
        top_k: int = 5,
        filters: Optional[dict] = None,
    ) -> list[SemanticItem]:
        """语义检索（可选接口，返回 SemanticItem）。

        默认实现为“不支持”。具体 store（SQLite/向量库）可覆盖此方法。
        """
        raise NotImplementedError("Semantic search is not supported by this store")

    @abstractmethod
    async def delete(self, item_id: str, namespace: str) -> bool:
        """删除指定记忆

        Args:
            item_id: 记忆 ID
            namespace: 命名空间
        Returns:
            是否删除成功
        """
        ...

    @abstractmethod
    async def clear_namespace(self, namespace: str) -> int:
        """清空某个命名空间下的所有记忆，返回删除数量

        Args:
            namespace: 命名空间
        Returns:
            删除数量
        """
        ...

    @abstractmethod
    async def ttl_evict(self, namespace: str, threshold_str: str) -> int:
        """删除 ``last_accessed_at < threshold_str`` 的行（仅限 namespace），返回删除数量。"""
        ...

    @abstractmethod
    async def capacity_evict(self, namespace: str, max_items: int) -> int:
        """若该 namespace 行数超过 ``max_items``，按 LRU 顺序删至不超上限，返回删除数量。"""
        ...
