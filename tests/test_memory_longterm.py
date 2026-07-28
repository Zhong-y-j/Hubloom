from __future__ import annotations

import asyncio
import math
import tempfile
from pathlib import Path

from config import HubloomConfig
from embedders.base import Embedder
from memory import create_memory_manager


class _DemoEmbedder(Embedder):
    """演示用：本地出向量，不调外部 embedding API。"""

    async def embed(self, texts: list[str]) -> list[list[float]]:
        out: list[list[float]] = []
        for text in texts:
            vec = [0.0] * 1024
            for ch in text or "":
                vec[hash(ch) % 1024] += 1.0
            n = math.sqrt(sum(x * x for x in vec)) or 1.0
            out.append([x / n for x in vec])
        return out


async def demo_longterm_memory() -> None:
    session_id = "demo-user-1"
    cfg = HubloomConfig.from_file("config/env.yaml")

    with tempfile.TemporaryDirectory() as tmp:

        # 创建记忆管理器
        memory = create_memory_manager(
            namespace=session_id,
            db_path=str(Path(tmp) / "memory.db"),
            vector_backend="qdrant",
            graph_backend="none",
            qdrant_url=cfg.qdrant_url,
            qdrant_api_key=cfg.qdrant_api_key,
            qdrant_collection=cfg.qdrant_collection,
            embedder=_DemoEmbedder(),
        )

        # 假 embedder 相似度偏低；演示关掉默认 0.55 门槛，否则会写成了却搜不到
        for name in ("episodic", "semantic"):
            handler = memory.handlers.get(name)
            if handler is not None:
                handler._score_threshold = 0.0

        # 1、写入情景笔记
        await memory.remember(
            memory_type="episodic",
            content="用户查询了 A 区柜子，得知 3 号空闲、5 号占用。",
        )
        # 2、写入语义笔记（偏好）
        await memory.remember(
            memory_type="semantic",
            content="用户偏好：查柜子时优先看 A 区。",
        )

        # 3、按问题检索（不是按时间拉聊天记录）
        result = await memory.recall(
            query="用户查柜子时有什么偏好？",
            top_k=5,
            mode="hybrid",
        )

        print("【session_id / namespace】", session_id)
        print("【召回条数】", len(result.items or []))
        print("【长期记忆】")
        for i, item in enumerate(result.items or [], 1):
            print(f"  [{i}] {item.content}")

        await memory.clear_all()


if __name__ == "__main__":
    asyncio.run(demo_longterm_memory())
