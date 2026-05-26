"""长期记忆召回与 ContextAssembler 输入适配。"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from memory.manager import MemoryManager, RecallResult
from memory.models import AssociativeRecallResult, EpisodicItem, SemanticItem


@dataclass
class MemoryRecallContext:
    """供 ContextAssembler 使用的长期记忆召回结果。"""

    memories: list[dict[str, Any]] = field(default_factory=list)
    graph_summary: str | None = None


class MemoryContextProvider:
    """从 MemoryManager 召回长期记忆，并规范化为 assembler 可消费的 dict 列表。"""

    def __init__(
        self,
        memory_manager: MemoryManager,
        *,
        hybrid_top_k: int = 5,
        associative_top_k: int = 8,
        include_associative: bool = True,
        associative_hops: int = 1,
    ) -> None:
        self._memory = memory_manager
        self.hybrid_top_k = hybrid_top_k
        self.associative_top_k = associative_top_k
        self.include_associative = include_associative
        self.associative_hops = associative_hops

    async def recall_for_context(self, query: str) -> MemoryRecallContext:
        """召回 episodic + semantic（hybrid），可选 associative 图摘要。"""
        query = (query or "").strip()
        if not query:
            return MemoryRecallContext()

        hybrid = await self._safe_recall_hybrid(query)
        memories = normalize_memory_items(hybrid)

        graph_summary: str | None = None
        if self.include_associative:
            graph = await self._safe_recall_associative(query)
            if graph is not None:
                graph_summary = format_associative_graph(graph)

        return MemoryRecallContext(
            memories=memories, graph_summary=graph_summary
        )

    async def _safe_recall_hybrid(self, query: str) -> RecallResult | None:
        try:
            return await self._memory.recall(
                query=query,
                top_k=self.hybrid_top_k,
                mode="hybrid",
            )
        except Exception:
            return None

    async def _safe_recall_associative(
        self, query: str
    ) -> AssociativeRecallResult | None:
        try:
            result: RecallResult = await self._memory.recall(
                query=query,
                memory_type="associative",
                top_k=self.associative_top_k,
                filters={
                    "hops": self.associative_hops,
                    "include_memory_refs": True,
                },
            )
        except Exception:
            return None
        return result.graph


def normalize_memory_items(recall: RecallResult | None) -> list[dict[str, Any]]:
    """将 recall.items 转为 assembler memories 参数格式。"""
    if recall is None or not recall.items:
        return []
    out: list[dict[str, Any]] = []
    for item in recall.items:
        row = memory_item_to_dict(item)
        if row:
            out.append(row)
    return out


def memory_item_to_dict(item: Any) -> dict[str, Any] | None:
    """单条长期记忆 → {content, score, memory_type}。"""
    if isinstance(item, dict):
        content = str(item.get("content", "")).strip()
        if not content:
            return None
        return {
            "content": content,
            "score": float(item.get("score", 0.7)),
            "memory_type": str(item.get("memory_type") or "memory"),
        }

    if isinstance(item, EpisodicItem):
        content = (item.content or "").strip()
        if not content:
            return None
        return {
            "content": content,
            "score": float(item.metadata.get("score", 0.75)),
            "memory_type": "episodic",
        }

    if isinstance(item, SemanticItem):
        content = (item.content or "").strip()
        if not content:
            return None
        return {
            "content": content,
            "score": float(item.metadata.get("score", 0.75)),
            "memory_type": "semantic",
        }

    content = str(getattr(item, "content", "")).strip()
    if not content:
        return None
    meta = getattr(item, "metadata", None)
    score = 0.75
    if isinstance(meta, dict) and meta.get("score") is not None:
        score = float(meta["score"])
    return {"content": content, "score": score, "memory_type": "memory"}


def format_associative_graph(graph: AssociativeRecallResult | None) -> str | None:
    """将图检索结果格式化为文本摘要。"""
    if graph is None:
        return None

    lines: list[str] = []
    if graph.seed:
        seed = graph.seed
        desc = f" — {seed.description}" if seed.description else ""
        lines.append(f"种子实体: {seed.name} ({seed.entity_type}){desc}")

    for rel in graph.relations:
        label = rel.relation_label or rel.relation_type
        lines.append(f"- {rel.from_name} --[{label}]--> {rel.to_name}")

    for entity in graph.entities:
        if graph.seed and entity.id == graph.seed.id:
            continue
        desc = f": {entity.description}" if entity.description else ""
        lines.append(f"- 实体 {entity.name} ({entity.entity_type}){desc}")

    for ref in graph.memory_refs:
        preview = (ref.content_preview or ref.memory_id or "").strip()
        if preview:
            lines.append(f"- 关联记忆({ref.memory_type}): {preview}")

    text = "\n".join(lines).strip()
    return text or None
