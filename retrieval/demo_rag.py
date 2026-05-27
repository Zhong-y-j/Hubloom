"""RAG 知识库冒烟：入库 + 检索。运行：PYTHONPATH=. uv run python retrieval/demo_rag.py"""

import asyncio
import os

from core import create_llm
from embedders.openai_embedder import OpenAIEmbedder
from retrieval.knowledge_base import KnowledgeBase
from retrieval.query_optimizer import QueryOptimizer

from tools.builtin import SearchDocumentsTool
from observability import setup_log

# 测试用文档路径（可按需改）
_DEFAULT_DOC = (
    "/Users/zhong/Desktop/Git-store/CODE/面试/AI项目个人工作内容及实现思路.docx"
)


async def main() -> None:
    setup_log()
    # 1. 创建嵌入器
    embedder = OpenAIEmbedder()
    query_optimizer = QueryOptimizer(create_llm())

    # 2. 创建知识库
    kb = KnowledgeBase(
        embedder=embedder,
        persist_dir="data/knowledge_db",
        query_optimizer=query_optimizer,
    )

    # kb.clear()
    # # 3. 添加文档（只需执行一次）
    # doc_id = await kb.add_document(
    #     "/Users/zhong/Desktop/Git-store/CODE/面试/AI项目个人工作内容及实现思路.docx"
    # )
    # print(f"文档已索引: {doc_id}")

    # # # 4. 搜索文档
    tool = SearchDocumentsTool(kb, top_k=3)
    result = await tool.execute(query="我一共做了几个AI项目", optimize="hyde")
    print(result)

    # result = await tool.execute(query="我一共做了几个AI项目", optimize="mqe")
    # print(result)

    # result = await tool.execute(query="我一共做了几个AI项目", optimize="none")
    # print(result)


if __name__ == "__main__":
    asyncio.run(main())
