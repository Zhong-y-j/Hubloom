"""批量记忆提炼：读取 conversation 片段 → LLM 产出 Experience Case JSON → 写入 Qdrant。

编排层（CortexAgent）只负责 recall；本模块供离线 worker / 定时任务调用。
"""

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from agents.agent_log import clip, memory_log
from core.models import Message, Role
from memory.experience_case import (
    BATCH_EXTRACTION_JSON_EXAMPLE,
    BatchExtractionResult,
    ExperienceCase,
    SemanticRule,
    parse_batch_extraction,
)
from memory.store.conversation_sqlite_store import ConversationMessageRecord

if TYPE_CHECKING:
    from core.provider import LLMProvider
    from memory.manager import MemoryManager
    from memory.types import AgentRoute

BATCH_CONSOLIDATION_SYSTEM = f"""你是记忆批量提炼助手。根据一段会话 transcript（含 user / assistant / tool），
提炼可长期保存的「案例」与「规则」。

规则：
- 每个用户意图（通常从一条 USER 开始到下一条 USER 之前）尽量对应一个 case
- case 必须包含：user_intent、approach、lesson；tools_used 来自 transcript 中的工具调用
- outcome：success / partial / failed / unknown；无充分证据时用 unknown
- user_satisfied：yes / no / unknown；只有 transcript 中后续用户明确表示不满/纠正时才标 no，不要猜测
- lesson：给下次处理的教训（工具顺序、缺参追问、避免的错误等）
- semantic_rules：从本段对话归纳的稳定规则（跨案例复用），不要写一次性事件
- 不要保存密码、密钥等敏感信息
- 若无值得保存的内容，cases 与 semantic_rules 返回空数组

只输出 JSON，格式示例：
{BATCH_EXTRACTION_JSON_EXAMPLE}
"""


def _content_text(content: str | list[dict[str, Any]]) -> str:
    if isinstance(content, str):
        return content
    try:
        return json.dumps(content, ensure_ascii=False)
    except (TypeError, ValueError):
        return str(content)


def format_conversation_segment(records: list[ConversationMessageRecord]) -> str:
    """将 conversation 片段格式化为 LLM 可读的 transcript。"""
    lines: list[str] = []
    for rec in records:
        msg = rec.message
        role = msg.role.value
        text = _content_text(msg.content).strip()

        if msg.role == Role.ASSISTANT and msg.tool_calls:
            names = ", ".join(tc.name for tc in msg.tool_calls if tc.name)
            prefix = f"[{rec.id}] assistant"
            if text:
                lines.append(f"{prefix}: {text}")
            lines.append(f"{prefix}: (tool_calls: {names})")
            continue

        if msg.role == Role.TOOL:
            name = msg.name or "tool"
            preview = clip(text, 400)
            lines.append(f"[{rec.id}] tool/{name}: {preview}")
            continue

        preview = clip(text, 800)
        lines.append(f"[{rec.id}] {role}: {preview}")

    return "\n".join(lines)


def split_conversation_turns(
    records: list[ConversationMessageRecord],
) -> list[list[ConversationMessageRecord]]:
    """按 USER 消息切分为多轮片段。"""
    turns: list[list[ConversationMessageRecord]] = []
    current: list[ConversationMessageRecord] = []
    for rec in records:
        if rec.message.role == Role.USER and current:
            turns.append(current)
            current = []
        current.append(rec)
    if current:
        turns.append(current)
    return turns


def _enrich_case(
    case: ExperienceCase,
    records: list[ConversationMessageRecord],
    *,
    session_id: str,
    route: AgentRoute | None,
) -> ExperienceCase:
    """补充来源会话与消息预览。"""
    case.ref_session_id = session_id
    if records:
        case.turn_start_id = records[0].id
        case.turn_end_id = records[-1].id
    if route:
        case.route = route

    for rec in records:
        msg = rec.message
        if msg.role == Role.USER and not case.user_message_preview:
            case.user_message_preview = clip(_content_text(msg.content), 200)
        if (
            msg.role == Role.ASSISTANT
            and not msg.tool_calls
            and not case.assistant_message_preview
        ):
            case.assistant_message_preview = clip(_content_text(msg.content), 200)
    return case


@dataclass
class BatchConsolidationWriteResult:
    """批量提炼写入结果。"""

    cases_written: list[str] = field(default_factory=list)
    semantic_rules_written: list[str] = field(default_factory=list)
    turns_processed: int = 0
    skipped: bool = False
    error: str | None = None

    @property
    def total_written(self) -> int:
        return len(self.cases_written) + len(self.semantic_rules_written)


class MemoryBatchConsolidator:
    """离线批量提炼：conversation 片段 → ExperienceCase / SemanticRule → Qdrant。"""

    def __init__(
        self,
        memory_manager: MemoryManager,
        llm: LLMProvider,
        *,
        min_segment_messages: int = 2,
    ) -> None:
        self._memory = memory_manager
        self._llm = llm
        self._min_segment_messages = min_segment_messages

    async def consolidate_session(
        self,
        session_id: str,
        *,
        limit: int | None = None,
        route: AgentRoute | None = None,
    ) -> BatchConsolidationWriteResult:
        """读取会话历史，按 USER 轮次逐段提炼并写入。"""
        records = await self._load_records(session_id, limit=limit)
        if len(records) < self._min_segment_messages:
            return BatchConsolidationWriteResult(skipped=True)

        turns = split_conversation_turns(records)
        merged = BatchConsolidationWriteResult()
        for turn in turns:
            if not any(r.message.role == Role.USER for r in turn):
                continue
            part = await self.consolidate_segment(
                session_id,
                turn,
                route=route,
            )
            merged.turns_processed += 1
            merged.cases_written.extend(part.cases_written)
            merged.semantic_rules_written.extend(part.semantic_rules_written)
            if part.error and not merged.error:
                merged.error = part.error

        if merged.total_written == 0:
            merged.skipped = True
        return merged

    async def consolidate_segment(
        self,
        session_id: str,
        records: list[ConversationMessageRecord],
        *,
        route: AgentRoute | None = None,
    ) -> BatchConsolidationWriteResult:
        """提炼单个 conversation 片段并写入 Qdrant。"""
        if len(records) < 1:
            return BatchConsolidationWriteResult(skipped=True)

        transcript = format_conversation_segment(records)
        if not transcript.strip():
            return BatchConsolidationWriteResult(skipped=True)

        try:
            extracted = await self.extract_from_transcript(transcript)
        except Exception as exc:
            return BatchConsolidationWriteResult(skipped=True, error=str(exc))

        if extracted.skipped:
            return BatchConsolidationWriteResult(skipped=True, error=extracted.error)

        for case in extracted.cases:
            _enrich_case(case, records, session_id=session_id, route=route)

        return await self.apply_extraction(extracted)

    async def extract_from_transcript(self, transcript: str) -> BatchExtractionResult:
        """LLM 从 transcript 提炼 cases / semantic_rules。"""
        prompt = (
            "以下是一段会话 transcript（方括号内为消息 id）：\n\n"
            f"{transcript.strip()}\n\n"
            "请提炼 cases 与 semantic_rules。"
        )
        out = await self._llm.generate(
            messages=[
                Message(role=Role.SYSTEM, content=BATCH_CONSOLIDATION_SYSTEM),
                Message(role=Role.USER, content=prompt),
            ],
            tools=None,
        )
        return parse_batch_extraction(out.content or "")

    async def apply_extraction(
        self,
        extracted: BatchExtractionResult,
    ) -> BatchConsolidationWriteResult:
        """将提炼结果写入 episodic / semantic（Qdrant）。"""
        result = BatchConsolidationWriteResult()
        if extracted.skipped:
            result.skipped = True
            result.error = extracted.error
            return result

        for case in extracted.cases:
            try:
                await self._memory.remember(
                    memory_type="episodic",
                    content=case.to_episodic_content(),
                    metadata=case.to_episodic_metadata(),
                )
                result.cases_written.append(case.to_episodic_content())
            except Exception as exc:
                memory_log(
                    "batch case write failed",
                    error=type(exc).__name__,
                    detail=clip(str(exc), 120),
                )
                if not result.error:
                    result.error = str(exc)

        for rule in extracted.semantic_rules:
            try:
                await self._memory.remember(
                    memory_type="semantic",
                    content=rule.to_semantic_content(),
                    metadata=rule.to_semantic_metadata(),
                )
                result.semantic_rules_written.append(rule.to_semantic_content())
            except Exception as exc:
                memory_log(
                    "batch semantic write failed",
                    error=type(exc).__name__,
                    detail=clip(str(exc), 120),
                )
                if not result.error:
                    result.error = str(exc)

        if result.total_written == 0:
            result.skipped = True
        return result

    async def _load_records(
        self,
        session_id: str,
        *,
        limit: int | None,
    ) -> list[ConversationMessageRecord]:
        handler = self._memory._conversation_handler()
        store = handler.store
        if limit is not None and limit > 0:
            return await asyncio.to_thread(store.get_recent_records, session_id, limit)
        return await asyncio.to_thread(store.get_all_records, session_id)
