"""RAG 知识库冒烟：入库 + 检索。运行：PYTHONPATH=. uv run python retrieval/demo_rag.py"""

import asyncio
import os

from core import create_llm
from memory.embedders.openai_embedder import OpenAIEmbedder
from retrieval.knowledge_base import KnowledgeBase
from retrieval.query_optimizer import QueryOptimizer

# 测试用文档路径（可按需改）
_DEFAULT_DOC = (
    "/Users/zhong/Desktop/Git-store/CODE/面试/AI项目个人工作内容及实现思路.docx"
)


async def _print_hits(label: str, results: list[dict]) -> None:
    print(f"\n--- {label}（{len(results)} 条）---")
    if not results:
        print("(无结果)")
        return
    for i, hit in enumerate(results, 1):
        meta = hit.get("metadata") or {}
        text = (hit.get("text") or "").strip().replace("\n", " ")
        preview = text[:120] + ("..." if len(text) > 120 else "")
        print(
            f"[{i}] score={hit.get('score', 0):.4f} "
            f"doc={meta.get('doc_name', '?')} "
            f"section={meta.get('section_title', meta.get('chunk_id', ''))}"
        )
        print(f"    {preview}")


async def main() -> None:
    embedder = OpenAIEmbedder()
    query_optimizer = QueryOptimizer(create_llm())

    kb = KnowledgeBase(
        embedder=embedder,
        persist_dir="data/knowledge_db",
        query_optimizer=query_optimizer,
    )

    doc_path = _DEFAULT_DOC
    query = "AI项目一共有几个项目"

    # 入库（设 RAG_SKIP_INDEX=1 可跳过，直接测已有 chroma 数据）
    if os.getenv("RAG_SKIP_INDEX", "").lower() not in ("1", "true", "yes"):
        kb.clear()
        doc_id = await kb.add_document(doc_path)
        print(f"文档已索引: {doc_id}")
        print(f"  路径: {doc_path}")
        docs = kb.get_document_list()
        print(f"  知识库文档数: {len(docs)}")
    else:
        print("跳过入库（RAG_SKIP_INDEX=1），使用已有索引")

    # 检索：默认向量
    hits = await kb.search(query, top_k=3, optimize="none")
    await _print_hits(f"检索 query={query!r} optimize=none", hits)

    # 可选：MQE / HyDE（需 LLM，稍慢）
    if os.getenv("RAG_TEST_OPTIMIZE", "").lower() in ("1", "true", "yes"):
        hits_mqe = await kb.search(query, top_k=3, optimize="mqe")
        await _print_hits("optimize=mqe", hits_mqe)
        hits_hyde = await kb.search(query, top_k=3, optimize="hyde")
        await _print_hits("optimize=hyde", hits_hyde)


if __name__ == "__main__":
    asyncio.run(main())
