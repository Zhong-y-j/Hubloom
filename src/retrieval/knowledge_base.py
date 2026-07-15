import os
import time
import uuid
from typing import Optional, List, Dict, Literal
import chromadb
from chromadb.config import Settings

from observability import log, logger
from .loader import DocumentLoader
from .semantic_splitter import SemanticSplitter
from embedders.base import Embedder
from .query_optimizer import QueryOptimizer


def _preview(text: str, limit: int = 80) -> str:
    text = (text or "").replace("\n", " ")
    return text if len(text) <= limit else text[:limit] + "…"


def _hits_preview(results: List[Dict], limit: int = 3) -> str:
    parts: list[str] = []
    for r in (results or [])[: max(0, limit)]:
        score = float(r.get("score", 0.0))
        meta = r.get("metadata") or {}
        source = meta.get("doc_name") or meta.get("section_path") or ""
        parts.append(f"{score:.3f}:{source}:{_preview(r.get('text', ''), 60)}")
    return "; ".join(parts)


class KnowledgeBase:
    """文档知识库，负责文档摄入与检索。

    设计思路：
        - 使用 MarkItDown 将任意格式文档转为 Markdown
        - 使用 SemanticSplitter 进行结构感知的语义分块
        - 使用 ChromaDB 同时存储文本、向量和元数据（双通道合一）
        - 存储丰富的元数据，方便溯源和上下文扩展
        - 检索时返回文本、元数据和相似度
    """

    def __init__(
        self,
        embedder: Embedder,
        persist_dir: str = "data/chroma_kb",
        collection_name: str = "documents",
        query_optimizer: QueryOptimizer | None = None,
    ):
        self.embedder = embedder
        self.collection_name = collection_name

        # 初始化 ChromaDB 持久化客户端
        self.client = chromadb.PersistentClient(
            path=persist_dir,
            settings=Settings(anonymized_telemetry=False),
        )
        self.collection = self.client.get_or_create_collection(name=collection_name)

        # 文档加载和分块工具
        self.loader = DocumentLoader()
        self.splitter = SemanticSplitter()
        self.query_optimizer = query_optimizer

    async def add_document(self, file_path: str, doc_id: Optional[str] = None) -> str:
        """加载并索引一个文档。

        Args:
            file_path: 文档路径
            doc_id: 文档 ID，不提供则自动生成

        Returns:
            文档 ID
        """
        if doc_id is None:
            doc_id = str(uuid.uuid4().hex)

        doc_name = os.path.basename(file_path)
        log("rag ingest start", file=file_path, doc_id=doc_id, doc_name=doc_name)
        t0 = time.perf_counter()
        try:
            return await self._add_document_impl(
                file_path, doc_id, doc_name, t0
            )
        except Exception as e:
            logger.warning(
                "rag ingest failed | file={} | doc_id={} | detail={}",
                file_path,
                doc_id,
                str(e)[:200],
            )
            raise

    async def _add_document_impl(
        self,
        file_path: str,
        doc_id: str,
        doc_name: str,
        t0: float,
    ) -> str:
        # 1. 加载文档（通过 MarkItDown 统一转为 Markdown）
        markdown_text = self.loader.load(file_path)

        # 2. 语义分块（返回块列表，每个块包含 content 和 metadata）
        chunk_dicts = self.splitter.split(markdown_text)
        if not chunk_dicts:
            logger.warning(
                "rag ingest empty chunks | file={} | doc_id={}",
                file_path,
                doc_id,
            )
            log("rag ingest done", doc_id=doc_id, chunks=0, duration_ms=0)
            return doc_id

        log("rag ingest chunks", doc_id=doc_id, chunks=len(chunk_dicts))

        # 3. 准备存入 ChromaDB 的数据
        ids = []
        documents = []
        embeddings = []
        metadatas = []

        source_type = os.path.splitext(file_path)[1].lower()
        indexed_at = time.strftime("%Y-%m-%d %H:%M:%S")

        # 逐块组装
        for chunk in chunk_dicts:
            chunk_content = chunk["content"]
            chunk_meta = chunk["metadata"]

            # 使用 SemanticSplitter 生成的 chunk_id 作为存储 ID
            storage_id = (
                f"{doc_id}_{chunk_meta.get('chunk_id', f'chunk_{uuid.uuid4().hex}')}"
            )
            ids.append(storage_id)

            documents.append(chunk_content)

            # 合并元数据：SemanticSplitter 的元数据 + 文档级元数据
            # ChromaDB 仅支持 str/int/float/bool，需过滤 None 值
            enriched_metadata = {
                k: v
                for k, v in {
                    **chunk_meta,
                    "doc_id": doc_id,
                    "doc_name": doc_name,
                    "source_type": source_type,
                    "indexed_at": indexed_at,
                }.items()
                if v is not None
            }
            metadatas.append(enriched_metadata)

        # 4. 分批生成嵌入向量（部分 API 有批量大小限制）
        batch_size = 8
        embeddings: List[List[float]] = []
        for start in range(0, len(documents), batch_size):
            batch = documents[start : start + batch_size]
            batch_embs = await self.embedder.embed(batch)
            embeddings.extend(batch_embs)

        # 5. 存入 ChromaDB（同时存储文档、向量和元数据）
        self.collection.add(
            ids=ids,
            documents=documents,
            embeddings=embeddings,
            metadatas=metadatas,
        )

        duration_ms = int((time.perf_counter() - t0) * 1000)
        log(
            "rag ingest done",
            doc_id=doc_id,
            chunks=len(chunk_dicts),
            duration_ms=duration_ms,
        )
        return doc_id

    async def search(
        self,
        query: str,
        top_k: int = 3,
        where: Optional[dict] = None,
        optimize: Literal["none", "mqe", "hyde"] = "none",  # 新增
    ) -> List[Dict]:
        """检索文档片段，可选查询优化。

        Args:
            query: 原始查询文本
            top_k: 返回结果数量
            where: ChromaDB 过滤条件
            optimize: 查询优化策略（none / mqe / hyde）

        Returns:
            检索结果列表
        """
        log(
            "rag search",
            query=_preview(query),
            top_k=top_k,
            optimize=optimize,
        )
        try:
            if optimize != "none" and self.query_optimizer:
                if optimize == "mqe":
                    queries = await self.query_optimizer.optimize(query, "mqe")
                    log("rag search mqe", variant_count=len(queries))
                    all_results = []
                    for q in queries:
                        all_results.extend(
                            await self._vector_search(q, top_k, where)
                        )
                    results = self._deduplicate_and_sort(all_results, top_k)
                elif optimize == "hyde":
                    hyde_text = await self.query_optimizer.optimize(query, "hyde")
                    log(
                        "rag search hyde",
                        hyde_len=len(hyde_text),
                        preview=_preview(hyde_text, 60),
                    )
                    results = await self._vector_search(hyde_text, top_k, where)
                else:
                    results = await self._vector_search(query, top_k, where)
            else:
                results = await self._vector_search(query, top_k, where)
        except Exception as e:
            logger.warning(
                "rag search failed | query={} | detail={}",
                _preview(query),
                str(e)[:200],
            )
            raise
        log(
            "rag search done",
            count=len(results),
            hits=_hits_preview(results),
        )
        return results

    def delete_document(self, doc_id: str) -> None:
        """删除指定文档的所有分块。"""
        try:
            self.collection.delete(where={"doc_id": doc_id})
        except Exception as e:
            logger.warning(
                "rag delete failed | doc_id={} | detail={}",
                doc_id,
                str(e)[:200],
            )
            raise
        log("rag delete", doc_id=doc_id)

    def clear(self) -> None:
        """清空整个知识库。"""
        try:
            self.client.delete_collection(self.collection_name)
            self.collection = self.client.get_or_create_collection(
                name=self.collection_name
            )
        except Exception as e:
            logger.warning(
                "rag clear failed | collection={} | detail={}",
                self.collection_name,
                str(e)[:200],
            )
            raise
        log("rag clear", collection=self.collection_name)

    async def _vector_search(
        self, query: str, top_k: int, where: Optional[dict]
    ) -> List[Dict]:
        """原有的向量检索逻辑，拆分为独立方法供内部复用。"""
        query_emb = (await self.embedder.embed([query]))[0]
        results = self.collection.query(
            query_embeddings=[query_emb],
            n_results=top_k,
            where=where,
            include=["documents", "metadatas", "distances"],
        )
        formatted = []
        if results and results["ids"] and results["ids"][0]:
            for i in range(len(results["ids"][0])):
                formatted.append(
                    {
                        "id": results["ids"][0][i],
                        "text": (
                            results["documents"][0][i] if results["documents"] else ""
                        ),
                        "metadata": (
                            results["metadatas"][0][i] if results["metadatas"] else {}
                        ),
                        "score": 1.0 - results["distances"][0][i],
                    }
                )
        return formatted

    @staticmethod
    def _deduplicate_and_sort(results: List[Dict], top_k: int) -> List[Dict]:
        """MQE 结果去重并按分数降序排列。"""
        seen_ids = set()
        unique_results = []
        for r in results:
            if r["id"] not in seen_ids:
                seen_ids.add(r["id"])
                unique_results.append(r)
        unique_results.sort(key=lambda x: x["score"], reverse=True)
        return unique_results[:top_k]

    def get_document_list(self) -> List[Dict]:
        """获取已索引文档的列表（去重后）。"""
        # 获取所有块的元数据
        all_metadatas = self.collection.get(include=["metadatas"])
        if not all_metadatas or not all_metadatas["metadatas"]:
            return []

        # 按 doc_id 去重，提取文档信息
        seen = set()
        doc_list = []
        for meta in all_metadatas["metadatas"]:
            doc_id = meta.get("doc_id")
            if doc_id and doc_id not in seen:
                seen.add(doc_id)
                doc_list.append(
                    {
                        "doc_id": doc_id,
                        "doc_name": meta.get("doc_name", ""),
                        "source_type": meta.get("source_type", ""),
                        "indexed_at": meta.get("indexed_at", ""),
                    }
                )
        return doc_list
