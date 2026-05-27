from typing import Any

from observability import log
from tools.base import BaseTool
from retrieval.knowledge_base import KnowledgeBase


def _preview(text: str, limit: int = 80) -> str:
    text = (text or "").replace("\n", " ")
    return text if len(text) <= limit else text[:limit] + "…"


class SearchDocumentsTool(BaseTool):
    """搜索文档知识库的工具。

    与记忆系统的 search_memory 工具并列，Agent 可按需调用。
    """

    name = "search_documents"
    description = (
        "在外部文档知识库中检索与 query 相关的片段。"
        "适用场景：当用户提问涉及产品手册、公司政策、技术文档等需要从文件中查找答案的内容时使用。"
        "当直接检索效果不理想时，可通过 optimize 参数启用查询优化："
        "hyde 适合抽象问题（如'产品定位是什么'），mqe 适合模糊问题（如'有哪些方法'）。"
    )
    parameters = {
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": "查询语句，建议使用自然语言描述，如 '请假审批流程'",
            },
            "optimize": {
                "type": "string",
                "enum": ["none", "hyde", "mqe"],
                "description": (
                    "查询优化策略。none: 直接检索（默认）；"
                    "hyde: 先生成假设答案再检索，适合抽象/概括性问题；"
                    "mqe: 多角度改写查询并行检索，适合模糊/开放性问题"
                ),
            },
        },
        "required": ["query"],
    }

    def __init__(self, kb: KnowledgeBase, top_k: int = 5):
        self.kb = kb
        self.top_k = top_k

    async def execute(
        self,
        query: str = "",
        optimize: str = "none",
        **_: Any,
    ) -> str:
        if not query:
            return "查询内容不能为空。"

        if optimize not in ("none", "hyde", "mqe"):
            optimize = "none"

        log(
            "rag tool search",
            query=_preview(query),
            optimize=optimize,
            top_k=self.top_k,
        )
        results = await self.kb.search(query, top_k=self.top_k, optimize=optimize)
        log("rag tool search done", count=len(results))
        if not results:
            return "未找到相关文档资料。"

        lines = []
        for i, doc in enumerate(results, 1):
            meta = doc.get("metadata", {})
            section = meta.get("section_path", "")
            source = meta.get("doc_name", "")
            score = doc.get("score", 0.0)

            header_parts = [f"[{i}]"]
            if source:
                header_parts.append(f"来源: {source}")
            if section:
                header_parts.append(f"章节: {section}")
            header_parts.append(f"相关度: {score:.2f}")

            lines.append(" | ".join(header_parts))
            lines.append(doc["text"])
            lines.append("")
        return "\n".join(lines)
