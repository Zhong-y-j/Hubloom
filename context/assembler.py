"""
GSSC 四阶段上下文装配器
"""

import re
from typing import List, Optional, Dict, Any
from core.models import Message, Role


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
    ) -> List[Message]:
        """组装最终发送给 LLM 的消息列表。

        Args:
            system_prompt: 系统角色设定和工具规则（必备）
            memories: 记忆条目列表（需含 content 属性或为 dict），来自 MemoryStore系统的检索结果。
            documents: RAG 结果列表，每条含 text, metadata, score，来自 RAG 系统的检索结果。
            histories: 历史对话消息（最近若干轮）
            current_task: 当前用户输入，将作为最后一条 USER 消息

        Returns:
            可直接传入 llm.generate_stream() 的消息列表。
        """
        # 1. Gather：收集所有候选内容，统一为 Message 格式并标记优先级/分数
        candidates: List[Dict[str, Any]] = self._gather(
            system_prompt, memories, documents, histories
        )

        # 2. Select：去重、评分、按 Token 预算筛选
        selected = self._select(candidates)

        # 3. Structure：组装为有序的 Message 列表
        messages = self._structure(selected, current_task)

        # 4. Compress：若超限，从最早的历史中裁剪
        return self._compress(messages)

    # ────── Gather ──────
    def _gather(
        self,
        system_prompt: str,
        memories: Optional[List[Any]],
        documents: Optional[List[Dict]],
        histories: Optional[List[Message]],
    ) -> List[Dict[str, Any]]:
        candidates = []

        # 系统指令（最高优先级，保留为 SYSTEM 消息）
        candidates.append(
            _make_candidate(
                type_="system", content=system_prompt, priority=100, score=1.0
            )
        )

        # 记忆（高于文档，作为 SYSTEM 消息注入）
        if memories:
            for mem in memories:
                # 兼容对象和字典格式
                content = getattr(mem, "content", mem.get("content", ""))
                if not content:
                    continue
                if isinstance(mem, dict):
                    score = float(mem.get("score", 0.7))
                else:
                    score = float(getattr(mem, "score", 0.7))
                candidates.append(
                    _make_candidate(
                        type_="memory",
                        content=f"[相关记忆] {content}",
                        priority=70,
                        score=score,
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
        document_items = []
        history_items = []

        for item in selected:
            if item["type"] == "system":
                system_items.append(item)
            elif item["type"] == "memory":
                memory_items.append(item)
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

        # 策略：固定保留首尾，从后往前填充中间部分
        # - 首部：第一条 SYSTEM（角色设定）
        # - 尾部：最后一条 USER（当前任务）
        # - 中间：从后往前贪心填充（优先保留最近的对话）

        head = messages[0]
        tail = messages[-1] if len(messages) > 1 else None
        middle = messages[1:-1] if len(messages) > 2 else []

        budget = self.max_tokens
        budget -= self._estimate_tokens(head.content)
        if tail:
            budget -= self._estimate_tokens(tail.content)

        kept_middle: list[Message] = []
        for msg in reversed(middle):
            tokens = self._estimate_tokens(msg.content)
            if tokens <= budget:
                kept_middle.append(msg)
                budget -= tokens

        kept_middle.reverse()

        result = [head] + kept_middle
        if tail:
            result.append(tail)
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


if __name__ == "__main__":
    from memory.store.conversation_sqlite_store import ConversationSQLitesStore

    SESSION_ID = "dev_record:scaffold"
    SYSTEM_PROMPT = (
        "你是一个 Agent 应用脚手架的开发助手。\n"
        "你熟悉 Python 异步编程、LLM Agent 架构、RAG、向量数据库等技术。\n"
        "请基于用户的历史对话和相关记忆，给出有针对性的建议。"
    )

    store = ConversationSQLitesStore()
    real_histories = store.get_recent(SESSION_ID, limit=20)

    memories = [
        {
            "content": "用户正在开发一个 Agent 应用脚手架，已完成 Memory、RAG、Context 模块",
            "score": 0.9,
        },
        {"content": "用户偏好独立子系统设计，RAG 与 Memory 分离", "score": 0.75},
    ]

    documents = [
        {
            "text": "ContextAssembler 遵循 GSSC 流水线：Gather 汇集多源信息，Select 去重评分筛选，Structure 组装消息列表，Compress 裁剪超限内容。",
            "metadata": {
                "section_path": "Context Engineering > GSSC",
                "doc_name": "架构设计文档",
            },
            "score": 0.88,
        },
        {
            "text": "ConversationStore 基于 SQLite 持久化对话历史，支持按 session_id 存取，配合 ContextAssembler 实现历史裁剪。",
            "metadata": {
                "section_path": "Context Engineering > 持久化",
                "doc_name": "架构设计文档",
            },
            "score": 0.80,
        },
    ]

    def _print_result(label: str, assembler: ContextAssembler, result: list[Message]):
        total_tokens = assembler._calculate_total(result)
        print(f"\n{'='*60}")
        print(f"  {label}")
        print(
            f"  消息数: {len(result)}  |  预算: {assembler.max_tokens}  |  实际: ~{total_tokens} tokens"
        )
        print(f"{'='*60}")
        for i, msg in enumerate(result):
            preview = msg.content[:120].replace("\n", " ")
            print(f"  [{i}] {msg.role.value:10s} | {preview}...")
        print()

    print(f"数据库中共 {store.count(SESSION_ID)} 条消息，取最近 20 条作为历史")
    print(
        f"历史消息角色分布: {', '.join(f'{m.role.value}' for m in real_histories[:6])}..."
    )

    for budget in [500, 1500, 4000]:
        asm = ContextAssembler(max_tokens=budget)
        result = asm.assemble(
            system_prompt=SYSTEM_PROMPT,
            memories=memories,
            documents=documents,
            histories=real_histories,
            current_task="接下来应该如何将 ContextAssembler 集成到 ReActAgent 中？",
        )
        _print_result(f"Token 预算 = {budget}", asm, result)

    store.close()
