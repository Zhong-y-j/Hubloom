"""
GSSC 四阶段上下文装配器。

历史会话单独做预算裁剪（成组保留 tool 链），裁完后再与 system / 记忆块组装。
"""

from __future__ import annotations

import json
import re
from typing import Any, Dict, List, Optional

from agent.agent_log import memory_log
from core.models import Message, Role

_MEMORY_TYPE_LABELS = {
    "episodic": "情景",
    "semantic": "语义",
}
def estimate_text_tokens(text: str) -> int:
    """粗估文本 token（与历史实现一致，供装配预算使用）。"""
    if not text:
        return 0
    chinese = len(re.findall(r"[\u4e00-\u9fff]", text))
    english_words = len(re.findall(r"[a-zA-Z]+", text))
    others = len(re.findall(r"[0-9]+", text))
    return int(chinese * 0.7 + english_words * 1.3 + others * 1.0)


def estimate_message_tokens(msg: Message) -> int:
    """粗估单条 Message（含 tool_calls / tool_call_id）占用。"""
    content = msg.content
    if isinstance(content, str):
        n = estimate_text_tokens(content)
    elif content is None:
        n = 0
    else:
        n = estimate_text_tokens(json.dumps(content, ensure_ascii=False))
    if msg.tool_calls:
        try:
            raw = json.dumps(
                [
                    {
                        "id": tc.id,
                        "name": tc.name,
                        "arguments": tc.arguments,
                    }
                    for tc in msg.tool_calls
                ],
                ensure_ascii=False,
            )
            n += estimate_text_tokens(raw)
        except Exception:
            n += 32 * len(msg.tool_calls)
    if msg.tool_call_id:
        n += estimate_text_tokens(msg.tool_call_id)
    if msg.name:
        n += estimate_text_tokens(msg.name)
    return n


def _tool_call_ids(msg: Message) -> set[str]:
    if not msg.tool_calls:
        return set()
    return {tc.id for tc in msg.tool_calls if tc.id}


def group_conversation_messages(messages: List[Message]) -> List[List[Message]]:
    """把会话历史切成可原子裁剪的组。

    - ``assistant(tool_calls)`` + 紧随其后、匹配其 id 的 ``tool`` 回包 → 一组
    - 其余 ``user`` / 普通 ``assistant`` → 单条一组
    - 悬空 ``tool``（前面没有对应 tool_calls）→ 单独记下，后续丢弃
    """
    groups: List[List[Message]] = []
    i = 0
    n = len(messages)
    while i < n:
        msg = messages[i]
        if msg.role == Role.ASSISTANT and msg.tool_calls:
            needed = _tool_call_ids(msg)
            group = [msg]
            j = i + 1
            while j < n and messages[j].role == Role.TOOL:
                group.append(messages[j])
                tid = messages[j].tool_call_id
                if tid in needed:
                    needed.discard(tid)
                j += 1
            groups.append(group)
            i = j
            continue
        if msg.role == Role.TOOL:
            # 悬空 tool：自成一组，trim 时丢弃
            groups.append([msg])
            i += 1
            continue
        groups.append([msg])
        i += 1
    return groups


def _is_complete_tool_group(group: List[Message]) -> bool:
    """assistant(tool_calls) 组是否收齐全部 tool 回包。"""
    if not group:
        return False
    head = group[0]
    if head.role != Role.ASSISTANT or not head.tool_calls:
        # 悬空 tool
        if head.role == Role.TOOL:
            return False
        return True
    needed = _tool_call_ids(head)
    if not needed:
        return False
    got = {
        m.tool_call_id
        for m in group[1:]
        if m.role == Role.TOOL and m.tool_call_id
    }
    return needed <= got


def trim_conversation_history(
    messages: List[Message],
    *,
    max_tokens: int,
) -> List[Message]:
    """仅对会话历史做预算裁剪：成组保留 tool 链，宁丢整组不留半截。

    从最近往前保留完整组；单组本身超过预算则整组丢弃并继续尝试更早组。
    不完整的 tool 链（缺回包 / 悬空 tool）直接丢弃，避免 API 400。
    """
    if max_tokens <= 0 or not messages:
        return []

    groups = group_conversation_messages(messages)
    clean: List[List[Message]] = []
    dropped_incomplete = 0
    for g in groups:
        if not _is_complete_tool_group(g):
            dropped_incomplete += 1
            continue
        clean.append(g)

    kept_rev: List[List[Message]] = []
    budget = max_tokens
    dropped_oversize = 0
    for g in reversed(clean):
        cost = sum(estimate_message_tokens(m) for m in g)
        if cost <= budget:
            kept_rev.append(g)
            budget -= cost
        elif cost > max_tokens:
            # 单组本身超过总预算：跳过，继续尝试更早小组
            dropped_oversize += 1
            continue
        else:
            # 剩余预算不够：停止，保留已选中的最近连续组
            break

    kept_rev.reverse()
    out = [m for g in kept_rev for m in g]
    if dropped_incomplete or dropped_oversize or len(out) < len(messages):
        memory_log(
            "history trim",
            before=len(messages),
            after=len(out),
            groups_before=len(groups),
            groups_kept=len(kept_rev),
            dropped_incomplete=dropped_incomplete,
            dropped_oversize=dropped_oversize,
            max_tokens=max_tokens,
        )
    return out


class ContextAssembler:
    """上下文装配器：将多源信息组装成可直接传给 LLM 的消息列表。

    流水线：
        1. 先装配 system / 记忆 / 文档等非历史块，并扣掉其 token
        2. 剩余预算只裁剪 ``histories``（成组保留 tool 链）
        3. 再拼 current_task（若有）

    Args:
        max_tokens: 上下文 Token 预算上限（含 system 与历史）。
        system_reserve_ratio: 预留给系统指令的比例（兼容旧参数；实际按 system 真实长度扣减）。
        min_relevance: 记忆/文档的最低相关性分数。
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
        """组装最终发送给 LLM 的消息列表。"""
        pinned = self._build_pinned(
            system_prompt=system_prompt,
            memories=memories,
            documents=documents,
            graph_summary=graph_summary,
        )
        pinned_tokens = sum(estimate_message_tokens(m) for m in pinned)
        task = (current_task or "").strip()
        task_tokens = estimate_text_tokens(task) if task else 0

        history_budget = self.max_tokens - pinned_tokens - task_tokens
        trimmed = trim_conversation_history(
            list(histories or []),
            max_tokens=max(0, history_budget),
        )

        out = [*pinned, *trimmed]
        if task:
            out.append(Message(role=Role.USER, content=task))

        memory_log(
            "assemble",
            pinned=len(pinned),
            history_in=len(histories or []),
            history_out=len(trimmed),
            total=len(out),
            history_budget=max(0, history_budget),
            max_tokens=self.max_tokens,
        )
        return out

    def _build_pinned(
        self,
        *,
        system_prompt: str,
        memories: Optional[List[Any]],
        documents: Optional[List[Dict]],
        graph_summary: Optional[str],
    ) -> List[Message]:
        """system + [MEMORY]/[GRAPH]/[DOCUMENTS]，不参与历史按条裁剪。"""
        messages: List[Message] = [
            Message(role=Role.SYSTEM, content=system_prompt or "")
        ]

        # 记忆 / 文档仍按分数过滤；预算上优先保证 system，其余能塞多少算多少
        system_tokens = estimate_message_tokens(messages[0])
        reserve = max(system_tokens, int(self.max_tokens * self.system_reserve_ratio))
        budget = max(0, self.max_tokens - reserve)

        mem_bits: list[str] = []
        if memories:
            scored: list[tuple[float, str]] = []
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
                if not content or score < self.min_relevance:
                    continue
                label = _MEMORY_TYPE_LABELS.get(memory_type, "相关")
                formatted = f"[{label}记忆 | 相关度: {score:.2f}] {content}"
                scored.append((score, formatted))
            scored.sort(key=lambda x: x[0], reverse=True)
            for score, formatted in scored:
                cost = estimate_text_tokens(formatted)
                if cost > budget:
                    continue
                mem_bits.append(formatted)
                budget -= cost

        if mem_bits:
            messages.append(
                Message(
                    role=Role.SYSTEM,
                    content="[MEMORY]\n" + "\n".join(mem_bits) + "\n[/MEMORY]",
                )
            )

        if graph_summary and graph_summary.strip():
            block = graph_summary.strip()
            cost = estimate_text_tokens(block)
            if cost <= budget:
                messages.append(
                    Message(
                        role=Role.SYSTEM,
                        content=f"[GRAPH]\n{block}\n[/GRAPH]",
                    )
                )
                budget -= cost

        doc_bits: list[str] = []
        if documents:
            docs_scored: list[tuple[float, str]] = []
            for doc in documents:
                text = doc.get("text", "")
                meta = doc.get("metadata", {}) or {}
                score = float(doc.get("score", 0.5))
                if score < self.min_relevance or not text:
                    continue
                section = meta.get("section_path", "")
                source = meta.get("doc_name", "未知文档")
                formatted = (
                    f"[来源: {source} | 章节: {section} | 相关度: {score:.2f}]\n{text}"
                )
                docs_scored.append((score, formatted))
            docs_scored.sort(key=lambda x: x[0], reverse=True)
            for score, formatted in docs_scored:
                cost = estimate_text_tokens(formatted)
                if cost > budget:
                    continue
                doc_bits.append(formatted)
                budget -= cost

        if doc_bits:
            messages.append(
                Message(
                    role=Role.SYSTEM,
                    content="[DOCUMENTS]\n" + "\n\n".join(doc_bits) + "\n[/DOCUMENTS]",
                )
            )

        return messages

    # 兼容旧调用 / 测试
    def _estimate_tokens(self, text: str) -> int:
        return estimate_text_tokens(text)

    def _calculate_total(self, messages: List[Message]) -> int:
        return sum(estimate_message_tokens(msg) for msg in messages)


def _make_candidate(
    type_: str,
    content: str,
    priority: int,
    score: float,
    original_role: str = "",
    message: Optional[Message] = None,
) -> Dict[str, Any]:
    """保留给可能的外部调用；主路径已不再依赖 candidate 列表。"""
    return {
        "type": type_,
        "content": content,
        "priority": priority,
        "score": score,
        "original_role": original_role,
        "message": message,
    }
