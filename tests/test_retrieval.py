from __future__ import annotations

import asyncio
import math
import tempfile
from pathlib import Path

from embedders.base import Embedder
from retrieval import create_knowledge_base


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


async def demo_retrieval() -> None:
    query = "介绍一下Hubloom"

    with tempfile.TemporaryDirectory() as tmp:
        doc_path = Path("docs/README.md")

        # 1、创建知识库（本地 Chroma + 假 embedder）
        kb = create_knowledge_base(
            persist_dir=str(Path(tmp) / "chroma_kb"),
            embedder=_DemoEmbedder(),
        )

        # 2、入库一篇文档
        doc_id = await kb.add_document(str(doc_path))

        # 3、按问题检索片段
        hits = await kb.search(query, top_k=3, optimize="none")

        print("【文档】", doc_path.name, "doc_id=", doc_id)
        print("【查询】", query)
        print("【命中条数】", len(hits))
        print("【检索结果】")
        for i, hit in enumerate(hits, 1):
            meta = hit.get("metadata") or {}
            score = float(hit.get("score") or 0.0)
            section = meta.get("section_path") or ""
            text = (hit.get("text") or "").replace("\n", " ")
            if len(text) > 120:
                text = text[:120] + "…"
            print(f"  [{i}] score={score:.3f} section={section!r}")
            print(f"      {text}")

        kb.clear()


if __name__ == "__main__":
    asyncio.run(demo_retrieval())
