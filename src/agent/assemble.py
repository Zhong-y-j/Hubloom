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
    RESPOND_A2UI_UI_DESCRIPTION,
    RESPOND_MARKDOWN_SYSTEM,
    THINK_SYSTEM_AFTER_TOOLS,
    THINK_SYSTEM_BEFORE_TOOLS,
)
from core.models import Message, Role
from mcp_adapter.gateway.catalog import format_catalog_for_prompt
from memory import ContextAssembler
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
    """Think 装配：旧历史走 32K 预算；本轮 turn_messages 全文追加、不裁剪。
    形状::
        [SYSTEM] + [更早会话（Assembler ≤ history_max_tokens）] + [本轮原文]
    """
    turn = list(turn_messages or [])
    all_rows = await load_conversation(memory, top_k=history_limit)
    prior = _strip_turn_suffix(all_rows, turn)
    # 旧历史可裁；预算只约束 prior，不包含本轮
    assembled = ContextAssembler(max_tokens=history_max_tokens).assemble(
        system_prompt=system_prompt,
        histories=prior,
        current_task="",  # 触发句在 turn_messages 里，避免重复 USER
    )
    # 本轮（含 TOOL 全文）强制接在后面
    out = [*assembled, *turn]
    agent_trace(
        "assemble think",
        prior=len(prior),
        turn=len(turn),
        assembled=len(assembled),
        total=len(out),
        has_tool=turn_has_tool_result(turn),
    )
    return out


def assemble_respond_markdown(
    *,
    system_prompt: str,
    think_content: str,
) -> list[Message]:
    """Respond(Markdown)：与 A2UI 相同，仅 system + 本轮最后一轮 Think 正文。"""
    body = (think_content or "").strip()
    agent_trace(
        "assemble respond",
        present_mode="markdown",
        think_len=len(body),
    )
    return [
        Message(role=Role.SYSTEM, content=system_prompt),
        Message(role=Role.USER, content=body),
    ]


def assemble_respond_a2ui(
    *,
    system_prompt: str,
    think_content: str,
) -> list[Message]:
    """Respond(A2UI)：仅官方 system + 本轮最后一轮 Think 正文。"""
    body = (think_content or "").strip()
    agent_trace(
        "assemble respond",
        present_mode="a2ui",
        think_len=len(body),
        system_len=len(system_prompt or ""),
    )
    return [
        Message(role=Role.SYSTEM, content=system_prompt),
        Message(role=Role.USER, content=body),
    ]
