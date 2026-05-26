from __future__ import annotations

from abc import ABC, abstractmethod


class Embedder(ABC):
    """Embedding 生成器抽象。

    设计目标：
    - 让上层（MemoryManager/工具）不绑定某个供应商。
    - 以后从 OpenAI（A）切换到本地 sentence-transformers（B）时，只替换实现类即可。
    """

    @abstractmethod
    async def embed(self, texts: list[str]) -> list[list[float]]:
        """为 texts 生成 embeddings，返回与 texts 等长的向量列表。"""
        raise NotImplementedError

