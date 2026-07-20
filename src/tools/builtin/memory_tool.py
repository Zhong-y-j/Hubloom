from typing import Any

from agent.agent_log import clip
from memory.memory_context import MemoryContextProvider
from memory.manager import MemoryManager
from observability import log
from tools.base import BaseTool


class SearchMemoryTool(BaseTool):
    """搜索长期记忆（情景 + 语义 + 可选联想图）。"""

    name = "search_memory"
    description = (
        "在长期记忆库中检索与用户 query 相关的情景记忆、语义记忆及实体关系。"
        "适用场景：需要回忆用户过往事实、偏好、项目背景，或实体间关系时使用。"
        "预取的 [MEMORY] 块不足时可主动调用本工具补充检索。"
    )
    parameters = {
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": "检索语句，如 '用户做过哪些 AI 项目' 或 '神灯AR'",
            },
            "include_graph": {
                "type": "boolean",
                "description": "是否同时检索联想记忆（实体关系），默认 true",
            },
        },
        "required": ["query"],
    }

    def __init__(
        self,
        memory_manager: MemoryManager,
        *,
        top_k: int = 5,
        include_graph: bool = True,
    ) -> None:
        self._provider = MemoryContextProvider(
            memory_manager,
            hybrid_top_k=top_k,
            include_associative=include_graph,
        )

    async def execute(
        self,
        query: str = "",
        include_graph: bool = True,
        **_: Any,
    ) -> str:
        if not query.strip():
            return "查询内容不能为空。"

        self._provider.include_associative = bool(include_graph)
        log(
            "memory tool search",
            query=clip(query, 80),
            include_graph=include_graph,
            top_k=self._provider.hybrid_top_k,
        )
        ctx = await self._provider.recall_for_context(query)
        log(
            "memory tool search done",
            memories=len(ctx.memories),
            has_graph=bool((ctx.graph_summary or "").strip()),
        )

        if not ctx.memories and not ctx.graph_summary:
            return "未找到相关长期记忆。"

        lines: list[str] = []
        for i, mem in enumerate(ctx.memories, 1):
            mtype = mem.get("memory_type", "memory")
            score = float(mem.get("score", 0.0))
            content = mem.get("content", "")
            lines.append(f"[{i}] ({mtype} | 相关度: {score:.2f}) {content}")

        if ctx.graph_summary:
            lines.append("")
            lines.append("[联想记忆]")
            lines.append(ctx.graph_summary)

        return "\n".join(lines)
