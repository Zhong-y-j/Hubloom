"""上下文装配：历史 + Journal 摘要 + 本轮轨迹（无 A2UI）。"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from core.models import Message, Role
from mcp_adapter.gateway.catalog import format_catalog_for_prompt
from memory.context import estimate_message_tokens, trim_conversation_history
from memory.manager import MemoryManager
from skill import build_skills_prompt, load_skills

from agent.agent_log import agent_trace
from agent.evidence import EvidenceJournal
from agent.prompts import AGENT_SYSTEM, AGENT_SYSTEM_AFTER_TOOLS


async def load_conversation(
    memory: MemoryManager,
    *,
    top_k: int = 40,
) -> list[Message]:
    recalled = await memory.recall(memory_type="conversation", top_k=top_k)
    return list(recalled.messages or [])


def turn_has_tool_result(turn_messages: list[Message] | None) -> bool:
    return any(m.role == Role.TOOL for m in (turn_messages or []))


def _strip_turn_suffix(
    histories: list[Message],
    turn_messages: list[Message],
) -> list[Message]:
    n = len(turn_messages)
    if n == 0 or len(histories) < n:
        return list(histories)
    return list(histories[:-n])


def build_agent_systems(
    *,
    skills_dir: str | Path,
    skills_exclude: list[str] | None = None,
    catalog: Any = None,
) -> tuple[str, str]:
    """返回 (工具前 system, 工具后短 system)。"""
    skills = load_skills(skills_dir, exclude=skills_exclude or [])
    skills_block = build_skills_prompt(skills).strip()
    catalog_block = ""
    if catalog is not None:
        catalog_block = format_catalog_for_prompt(catalog).strip()

    before_parts = [AGENT_SYSTEM.strip()]
    if skills_block:
        before_parts.append(skills_block)
    if catalog_block:
        before_parts.append(catalog_block)
    before = "\n\n".join(before_parts)
    # 工具后只用短提示，避免反复灌长目录
    after = AGENT_SYSTEM_AFTER_TOOLS.strip()
    return before, after


def select_system(
    *,
    system_before: str,
    system_after: str,
    turn_messages: list[Message] | None,
) -> str:
    if turn_has_tool_result(turn_messages):
        return system_after
    return system_before


async def assemble_messages(
    memory: MemoryManager,
    *,
    system_prompt: str,
    turn_messages: list[Message] | None = None,
    journal: EvidenceJournal | None = None,
    history_limit: int = 40,
    history_max_tokens: int = 32_000,
) -> list[Message]:
    turn = list(turn_messages or [])
    all_rows = await load_conversation(memory, top_k=history_limit)
    prior = _strip_turn_suffix(all_rows, turn)

    system_msg = Message(role=Role.SYSTEM, content=system_prompt)
    journal_msg: Message | None = None
    if journal is not None:
        block = journal.summary_for_prompt()
        if block:
            journal_msg = Message(role=Role.SYSTEM, content=block)

    overhead = estimate_message_tokens(system_msg)
    if journal_msg is not None:
        overhead += estimate_message_tokens(journal_msg)
    history_budget = max(0, history_max_tokens - overhead)
    trimmed = trim_conversation_history(prior, max_tokens=history_budget)

    out = [system_msg, *trimmed]
    if journal_msg is not None:
        out.append(journal_msg)
    out.extend(turn)
    agent_trace(
        "assemble",
        prior=len(prior),
        history_out=len(trimmed),
        turn=len(turn),
        journal_entries=len(journal.entries) if journal else 0,
        total=len(out),
    )
    return out
