"""
GSSC 四阶段上下文装配器
"""

import re
from typing import List, Optional, Dict, Any

from agents.core.agent_log import memory_log
from core.models import Message, Role

_MEMORY_TYPE_LABELS = {
    "episodic": "情景",
    "semantic": "语义",
}
_PINNED_SYSTEM_TAGS = ("[MEMORY]", "[DOCUMENTS]", "[GRAPH]")


class ContextAssembler:
    """上下文装配器：将多源信息组装成可直接传给 LLM 的消息列表。

    遵循 GSSC 流水线，输出保持多角色多轮结构。

    Args:
        max_tokens: 上下文的 Token 预算上限，作用：限制上下文消息的总长度，避免超长。
        system_reserve_ratio: 预留给系统指令和规则的比例（0~1），作用：预留给系统指令和规则，避免超长。
        min_relevance: 记忆/文档的最低相关性分数，作用：过滤掉不相关的记忆/文档。

    Actions:
        - assemble: 组装最终发送给 LLM 的消息列表
    """

    def __init__(
        self,
        max_tokens: int = 3000,
        system_reserve_ratio: float = 0.2,
        min_relevance: float = 0.3,
    ):
        self.max_tokens = max_tokens
        self.system_reserve_ratio = system_reserve_ratio
        self.min_relevance = min_relevance

    def assemble(
        self,
        system_prompt: str,
        memories: Optional[List[Any]] = None,
        documents: Optional[List[Dict]] = None,
        histories: Optional[List[Message]] = None,
        current_task: str = "",
        graph_summary: Optional[str] = None,
    ) -> List[Message]:
        """组装最终发送给 LLM 的消息列表。

        Args:
            system_prompt: 系统角色设定和工具规则（必备）
            memories: 长期记忆条目（episodic/semantic），来自 MemoryContextProvider
            documents: RAG 结果列表，每条含 text, metadata, score
            histories: 历史对话消息（最近若干轮）
            current_task: 当前用户输入，将作为最后一条 USER 消息
            graph_summary: 联想记忆图摘要文本（associative recall 格式化结果）

        Returns:
            可直接传入 llm.generate_stream() 的消息列表。
        """
        # 1. Gather：收集所有候选内容，统一为 Message 格式并标记优先级/分数
        candidates: List[Dict[str, Any]] = self._gather(
            system_prompt, memories, documents, histories, graph_summary
        )

        # 2. Select：去重、评分、按 Token 预算筛选
        selected = self._select(candidates)

        # 3. Structure：组装为有序的 Message 列表
        messages = self._structure(selected, current_task)

        # 4. Compress：若超限，从最早的历史中裁剪
        compressed = self._compress(messages)
        if len(compressed) < len(messages):
            memory_log(
                "assemble compressed",
                before=len(messages),
                after=len(compressed),
                max_tokens=self.max_tokens,
            )
        return compressed

    # ────── Gather ──────
    def _gather(
        self,
        system_prompt: str,
        memories: Optional[List[Any]],
        documents: Optional[List[Dict]],
        histories: Optional[List[Message]],
        graph_summary: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        candidates = []

        # 系统指令（最高优先级，保留为 SYSTEM 消息）
        candidates.append(
            _make_candidate(
                type_="system", content=system_prompt, priority=100, score=1.0
            )
        )

        # 长期记忆（episodic / semantic）
        if memories:
            for mem in memories:
                content = getattr(mem, "content", None)
                memory_type = ""
                score = 0.7
                if isinstance(mem, dict):
                    content = mem.get("content", "")
                    memory_type = str(mem.get("memory_type") or "")
                    score = float(mem.get("score", 0.7))
                else:
                    content = content or ""
                    meta = getattr(mem, "metadata", None)
                    if isinstance(meta, dict) and meta.get("score") is not None:
                        score = float(meta["score"])
                if not content:
                    continue
                label = _MEMORY_TYPE_LABELS.get(memory_type, "相关")
                formatted = f"[{label}记忆 | 相关度: {score:.2f}] {content}"
                candidates.append(
                    _make_candidate(
                        type_="memory",
                        content=formatted,
                        priority=70,
                        score=score,
                    )
                )

        # 联想记忆图摘要
        if graph_summary and graph_summary.strip():
            candidates.append(
                _make_candidate(
                    type_="graph",
                    content=graph_summary.strip(),
                    priority=68,
                    score=0.72,
                )
            )

        # 文档（RAG 结果）
        if documents:
            for doc in documents:
                text = doc.get("text", "")
                meta = doc.get("metadata", {})
                score = doc.get("score", 0.5)
                section = meta.get("section_path", "")
                source = meta.get("doc_name", "未知文档")
                formatted = (
                    f"[来源: {source} | 章节: {section} | 相关度: {score:.2f}]\n{text}"
                )
                candidates.append(
                    _make_candidate(
                        type_="document",
                        content=formatted,
                        priority=50,
                        score=score,
                    )
                )

        # 历史对话（成对保留，按时间排序）
        if histories:
            for msg in histories:
                candidates.append(
                    _make_candidate(
                        type_="history",
                        content=msg.content,
                        priority=30,
                        score=0.5,
                        original_role=msg.role.value,
                    )
                )

        return candidates

    # ────── Select ──────
    def _select(self, candidates: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        # 去重（基于相同 type 和 content 前缀，只保留最高分）
        deduped: List[Dict[str, Any]] = []
        seen = set()
        for c in sorted(
            candidates, key=lambda x: (x["priority"], x["score"]), reverse=True
        ):
            # 历史消息不去重，每条都独立
            if c["type"] == "history":
                deduped.append(c)
                continue
            fingerprint = (c["type"], c["content"][:50])  # 首部指纹
            if fingerprint not in seen:
                seen.add(fingerprint)
                deduped.append(c)
        # 重新按 priority 排序
        deduped.sort(key=lambda x: (x["priority"], x["score"]), reverse=True)

        # 按分数阈值过滤（系统指令保留）
        filtered = [
            c
            for c in deduped
            if c["type"] == "system" or c["score"] >= self.min_relevance
        ]

        # 计算预算：系统指令预留
        system_budget = int(self.max_tokens * self.system_reserve_ratio)
        other_budget = self.max_tokens - system_budget

        selected: List[Dict[str, Any]] = []
        used_tokens = 0

        # 第一步：强制保留系统指令
        for c in filtered:
            if c["type"] == "system":
                selected.append(c)
                used_tokens += self._estimate_tokens(c["content"])
                break

        # 第二步：贪心填充记忆、文档、历史（优先级顺序已排序）
        for c in filtered:
            if c["type"] == "system":
                continue
            tokens = self._estimate_tokens(c["content"])
            if used_tokens + tokens <= other_budget:
                selected.append(c)
                used_tokens += tokens
            else:
                # 预算用尽，后续不再添加（历史消息可能会在 compress 阶段被整条丢弃，这里暂不处理）
                pass

        return selected

    # ────── Structure ──────
    def _structure(
        self, selected: List[Dict[str, Any]], current_task: str
    ) -> List[Message]:
        messages: List[Message] = []

        # 分组
        system_items = []
        memory_items = []
        graph_items = []
        document_items = []
        history_items = []

        for item in selected:
            if item["type"] == "system":
                system_items.append(item)
            elif item["type"] == "memory":
                memory_items.append(item)
            elif item["type"] == "graph":
                graph_items.append(item)
            elif item["type"] == "document":
                document_items.append(item)
            elif item["type"] == "history":
                history_items.append(item)

        # 1) 系统指令（保持在最开始）
        for item in system_items:
            messages.append(Message(role=Role.SYSTEM, content=item["content"]))

        # 2) 记忆块（作为单独的 SYSTEM 消息）
        if memory_items:
            mem_block = (
                "[MEMORY]\n"
                + "\n".join(item["content"] for item in memory_items)
                + "\n[/MEMORY]"
            )
            messages.append(Message(role=Role.SYSTEM, content=mem_block))

        if graph_items:
            graph_block = (
                "[GRAPH]\n"
                + "\n".join(item["content"] for item in graph_items)
                + "\n[/GRAPH]"
            )
            messages.append(Message(role=Role.SYSTEM, content=graph_block))

        # 3) 文档块（作为单独的 SYSTEM 消息）
        if document_items:
            doc_block = (
                "[DOCUMENTS]\n"
                + "\n\n".join(item["content"] for item in document_items)
                + "\n[/DOCUMENTS]"
            )
            messages.append(Message(role=Role.SYSTEM, content=doc_block))

        # 4) 历史对话（保留原角色）
        _role_map = {
            "user": Role.USER,
            "assistant": Role.ASSISTANT,
            "tool": Role.TOOL,
            "system": Role.SYSTEM,
        }
        for item in history_items:
            role = _role_map.get(item.get("original_role", ""), Role.USER)
            messages.append(Message(role=role, content=item["content"]))

        # 5) 当前任务（作为最后一条 USER 消息）
        if current_task.strip():
            messages.append(Message(role=Role.USER, content=current_task))

        return messages

    # ────── Compress ──────
    def _compress(self, messages: List[Message]) -> List[Message]:
        total = sum(self._estimate_tokens(msg.content) for msg in messages)
        if total <= self.max_tokens:
            return messages

        if not messages:
            return messages

        pinned: list[Message] = []
        rest_start = 0

        pinned.append(messages[0])
        rest_start = 1

        while rest_start < len(messages):
            msg = messages[rest_start]
            if msg.role == Role.SYSTEM and any(
                tag in msg.content for tag in _PINNED_SYSTEM_TAGS
            ):
                pinned.append(msg)
                rest_start += 1
            else:
                break

        tail: Message | None = None
        if len(messages) > rest_start and messages[-1].role == Role.USER:
            tail = messages[-1]
            middle = messages[rest_start:-1]
        else:
            middle = messages[rest_start:]

        budget = self.max_tokens
        budget -= sum(self._estimate_tokens(msg.content) for msg in pinned)
        if tail:
            budget -= self._estimate_tokens(tail.content)

        kept_middle: list[Message] = []
        for msg in reversed(middle):
            tokens = self._estimate_tokens(msg.content)
            if tokens <= budget:
                kept_middle.append(msg)
                budget -= tokens

        kept_middle.reverse()

        result = pinned + kept_middle
        if tail:
            result.append(tail)
        dropped = len(middle) - len(kept_middle)
        if dropped > 0:
            memory_log(
                "context compress",
                dropped_history=dropped,
                kept_history=len(kept_middle),
                total_before=len(messages),
                total_after=len(result),
                max_tokens=self.max_tokens,
            )
        return result

    def _calculate_total(self, messages: List[Message]) -> int:
        return sum(self._estimate_tokens(msg.content) for msg in messages)

    # ────── 辅助：Token 估算 ──────
    @staticmethod
    def _estimate_tokens(text: str) -> int:
        if not text:
            return 0
        chinese = len(re.findall(r"[\u4e00-\u9fff]", text))
        english_words = len(re.findall(r"[a-zA-Z]+", text))
        others = len(re.findall(r"[0-9]+", text))
        return int(chinese * 0.7 + english_words * 1.3 + others * 1.0)


def _make_candidate(
    type_: str,
    content: str,
    priority: int,
    score: float,
    original_role: str = "",
) -> Dict[str, Any]:
    return {
        "type": type_,
        "content": content,
        "priority": priority,
        "score": score,
        "original_role": original_role,
    }
