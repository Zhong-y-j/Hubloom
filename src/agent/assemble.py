"""Agent 上下文装配：system 拼装 + Think/Respond messages。
Orchestrator / 测试调用这里；loop（think/execute/respond）只消费已拼好的 messages。
"""

from __future__ import annotations
from pathlib import Path
from typing import Any
from a2ui.basic_catalog.provider import BasicCatalog
from a2ui.schema.constants import VERSION_0_9
from a2ui.schema.manager import A2uiSchemaManager
from agent.agent_log import agent_trace
from agent.prompts import (
    PRESENT_SYSTEM,
    RESPOND_A2UI_UI_DESCRIPTION,
    RESPOND_MARKDOWN_SYSTEM,
    THINK_SYSTEM_AFTER_TOOLS,
    THINK_SYSTEM_BEFORE_TOOLS,
)
from core.models import Message, Role
from mcp_adapter.gateway.catalog import format_catalog_for_prompt
from memory.context import estimate_message_tokens, trim_conversation_history
from memory.manager import MemoryManager
from skill import build_skills_prompt, load_skills


async def load_conversation(
    memory: MemoryManager,
    *,
    top_k: int = 40,
) -> list[Message]:
    """从 conversation 召回最近消息（时间正序）。"""
    recalled = await memory.recall(memory_type="conversation", top_k=top_k)
    return list(recalled.messages or [])


def turn_has_tool_result(turn_messages: list[Message] | None) -> bool:
    """本轮轨迹里是否已有 tool 回传（用于切换 Think 提示词）。"""
    return any(m.role == Role.TOOL for m in (turn_messages or []))


_GROUNDING_HEADER = (
    "【本轮事实 · 仅可引用下列内容，禁止编造未出现的实体/行/字段】"
)


def extract_respond_grounding(
    turn_messages: list[Message] | None,
    *,
    max_chars: int = 3500,
) -> str:
    """从本轮 tool 回传摘录事实，供 Respond 锚定（防幻觉）。

    优先保留 ``hubloom.a2ui_action`` 与较新的 ``call_api`` 结果。
    """
    tools: list[Message] = [
        m for m in (turn_messages or []) if m.role == Role.TOOL and (m.content or "").strip()
    ]
    if not tools:
        return ""

    def _prio(item: tuple[int, Message]) -> tuple[int, int]:
        idx, m = item
        name = (m.name or "").strip()
        # 人机动作最优先；业务 call_api 次之；其余靠后
        if name == "hubloom.a2ui_action" or "人机动作" in (m.content or ""):
            bucket = 0
        elif name == "call_api" or '"tool"' in (m.content or "")[:80]:
            bucket = 1
        else:
            bucket = 2
        return (bucket, -idx)

    ordered = [m for _, m in sorted(enumerate(tools), key=_prio)]
    chunks: list[str] = []
    used = 0
    for m in ordered:
        text = (m.content or "").strip()
        label = (m.name or "tool").strip() or "tool"
        block = f"({label})\n{text}"
        if used + len(block) + 2 > max_chars:
            remain = max_chars - used - 2
            if remain < 80:
                break
            block = block[:remain] + "…"
            chunks.append(block)
            break
        chunks.append(block)
        used += len(block) + 2
    if not chunks:
        return ""
    return _GROUNDING_HEADER + "\n" + "\n---\n".join(chunks)


def build_think_system(
    *,
    skills_dir: Path,
    skills_exclude: list[str] | None = None,
    catalog: Any | None = None,
    phase: str = "before_tools",
) -> str:
    """拼装 Think system。

    - ``before_tools``：THINK_SYSTEM_BEFORE_TOOLS + skills +（可选）API 目录
    - ``after_tools``：仅 THINK_SYSTEM_AFTER_TOOLS（不再挂长目录，降低复述 schema）
    """
    if phase == "after_tools":
        return THINK_SYSTEM_AFTER_TOOLS.strip()

    parts = [THINK_SYSTEM_BEFORE_TOOLS.strip()]
    skills = load_skills(skills_dir, exclude=skills_exclude or [])
    skills_text = build_skills_prompt(skills).strip()
    if skills_text:
        parts.append(skills_text)
    if catalog is not None:
        catalog_text = format_catalog_for_prompt(catalog).strip()
        if catalog_text:
            parts.append(catalog_text)
    return "\n\n".join(parts)


def build_think_systems(
    *,
    skills_dir: Path,
    skills_exclude: list[str] | None = None,
    catalog: Any | None = None,
) -> tuple[str, str]:
    """返回 ``(工具前 system, 工具后 system)``。"""
    before = build_think_system(
        skills_dir=skills_dir,
        skills_exclude=skills_exclude,
        catalog=catalog,
        phase="before_tools",
    )
    after = build_think_system(
        skills_dir=skills_dir,
        skills_exclude=skills_exclude,
        catalog=catalog,
        phase="after_tools",
    )
    return before, after


def select_think_system(
    *,
    think_system_before: str,
    think_system_after: str,
    turn_messages: list[Message] | None,
) -> str:
    """按本轮是否已有 tool 结果选择 Think system。"""
    if turn_has_tool_result(turn_messages):
        return think_system_after
    return think_system_before


def build_respond_markdown_system() -> str:
    return RESPOND_MARKDOWN_SYSTEM.strip()


def build_respond_a2ui_system(*, ui_description: str | None = None) -> str:
    """Respond(A2UI) system：SchemaManager 官方 prompt（含 schema）。

    ``ui_description`` 默认用 ``RESPOND_A2UI_UI_DESCRIPTION``（布局约定）；
    传入非空字符串可覆盖；传 ``""`` 则不加布局段。
    """
    if ui_description is None:
        ui_description = RESPOND_A2UI_UI_DESCRIPTION.strip()
    manager = A2uiSchemaManager(
        version=VERSION_0_9,
        catalogs=[BasicCatalog.get_config(version=VERSION_0_9)],
    )
    return manager.generate_system_prompt(
        role_description=(
            "You are a helpful assistant. When the user needs an interactive list "
            "or form, your final output MUST include valid A2UI UI JSON messages.\n"
            "LANGUAGE (hard rule): All user-visible text MUST be Simplified Chinese "
            "(简体中文), including: conversational text outside <a2ui-json> blocks, "
            "and every UI string inside A2UI (titles, labels, button text, helper "
            "hints, validation messages, option labels, placeholders). "
            "Do NOT use English for those strings. "
            "JSON keys, component type names, path/field names, and enum values "
            "required by the API/schema (e.g. available/pending/sold) may stay "
            "in English as required by the schema."
        ),
        workflow_description=(
            "Emit A2UI for progressive streaming. HARD RULES (violations are errors):\n"
            "1) Use EXACTLY three separate blocks, each wrapped in its own "
            "<a2ui-json>...</a2ui-json>. Each block MUST contain ONE JSON object "
            "(one message). NEVER put a JSON array of multiple messages inside one block.\n"
            "2) Emit blocks in this exact order, finishing each block (including the "
            "closing </a2ui-json>) before starting the next:\n"
            "   (1) createSurface\n"
            "   (2) updateComponents — full component tree / form scaffold first\n"
            "   (3) updateDataModel — values / empty defaults last\n"
            "3) NEVER emit updateDataModel before updateComponents.\n"
            "4) NEVER merge createSurface + updateComponents + updateDataModel into "
            "one <a2ui-json> block.\n"
            "Reason: the client renders each closed block immediately; components "
            "must arrive before data so the empty form framework can appear first."
        ),
        ui_description=ui_description,
        include_schema=True,
        include_examples=False,
    )


def _strip_turn_suffix(
    histories: list[Message],
    turn_messages: list[Message],
) -> list[Message]:
    """从全量召回里去掉本轮已落库的后缀，避免与 turn_messages 重复。"""
    n = len(turn_messages)
    if n == 0 or len(histories) < n:
        return list(histories)
    # run_stream 里 remember 顺序与 turn_messages 一致，直接剥尾部
    return list(histories[:-n])


async def assemble_think(
    memory: MemoryManager,
    *,
    system_prompt: str,
    turn_messages: list[Message] | None = None,
    history_limit: int = 40,
    history_max_tokens: int = 32_000,
) -> list[Message]:
    """Think 装配：先只裁历史，再与 system / 本轮组装。

    形状::
        [SYSTEM] + [裁剪后的更早会话] + [本轮 turn_messages 原文（不裁）]

    历史裁剪成组保留 ``assistant(tool_calls)+tool``，不把 system/skill 卷入按条丢弃。
    """
    turn = list(turn_messages or [])
    all_rows = await load_conversation(memory, top_k=history_limit)
    prior = _strip_turn_suffix(all_rows, turn)

    system_msg = Message(role=Role.SYSTEM, content=system_prompt)
    history_budget = max(0, history_max_tokens - estimate_message_tokens(system_msg))
    trimmed = trim_conversation_history(prior, max_tokens=history_budget)

    out = [system_msg, *trimmed, *turn]
    agent_trace(
        "assemble think",
        prior=len(prior),
        history_out=len(trimmed),
        turn=len(turn),
        total=len(out),
        history_budget=history_budget,
        has_tool=turn_has_tool_result(turn),
    )
    return out


def _respond_user_body(think_content: str, grounding: str = "") -> str:
    think = (think_content or "").strip()
    facts = (grounding or "").strip()
    if think and facts:
        return f"{think}\n\n{facts}"
    return think or facts


def assemble_respond_markdown(
    *,
    system_prompt: str,
    think_content: str,
    grounding: str = "",
) -> list[Message]:
    """Respond(Markdown)：system + Think 结论 + 可选本轮 tool/action 事实。"""
    body = _respond_user_body(think_content, grounding)
    agent_trace(
        "assemble respond",
        present_mode="markdown",
        think_len=len((think_content or "").strip()),
        grounding_len=len((grounding or "").strip()),
    )
    return [
        Message(role=Role.SYSTEM, content=system_prompt),
        Message(role=Role.USER, content=body),
    ]


def assemble_respond_a2ui(
    *,
    system_prompt: str,
    think_content: str,
    grounding: str = "",
) -> list[Message]:
    """Respond(A2UI)：官方 system + Think 结论 + 可选本轮事实。"""
    body = _respond_user_body(think_content, grounding)
    agent_trace(
        "assemble respond",
        present_mode="a2ui",
        think_len=len((think_content or "").strip()),
        grounding_len=len((grounding or "").strip()),
        system_len=len(system_prompt or ""),
    )
    return [
        Message(role=Role.SYSTEM, content=system_prompt),
        Message(role=Role.USER, content=body),
    ]


def assemble_present(*, think_content: str) -> list[Message]:
    """Present：system + Think 正文，判断 NEED_A2UI。"""
    body = (think_content or "").strip() or "（空 Think）"
    agent_trace("assemble present", think_len=len(body))
    return [
        Message(role=Role.SYSTEM, content=PRESENT_SYSTEM.strip()),
        Message(role=Role.USER, content=body),
    ]
