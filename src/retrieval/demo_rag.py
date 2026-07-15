"""RAG 知识库冒烟：入库 + 检索。运行：PYTHONPATH=. uv run python -m retrieval.demo_rag"""

import asyncio

from core import create_llm
from embedders.openai_embedder import OpenAIEmbedder
from hubloom.config import HubloomConfig
from retrieval.knowledge_base import KnowledgeBase
from retrieval.query_optimizer import QueryOptimizer

from tools.builtin import SearchDocumentsTool
from observability import setup_log


async def main() -> None:
    setup_log()
    cfg = HubloomConfig.from_file("config/env.yaml")
    embedder = OpenAIEmbedder(
        api_key=cfg.openai_api_key,
        base_url=cfg.openai_base_url,
    )
    query_optimizer = QueryOptimizer(
        create_llm(
            api_key=cfg.openai_api_key,
            model=cfg.openai_model,
            base_url=cfg.openai_base_url,
        )
    )

    kb = KnowledgeBase(
        embedder=embedder,
        persist_dir=(cfg.kb_dir or "data/knowledge_db").strip()
        or "data/knowledge_db",
        query_optimizer=query_optimizer,
    )

    tool = SearchDocumentsTool(kb, top_k=3)
    result = await tool.execute(query="我一共做了几个AI项目", optimize="hyde")
    print(result)


if __name__ == "__main__":
    asyncio.run(main())
