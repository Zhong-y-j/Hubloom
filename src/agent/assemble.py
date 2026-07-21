"""Agent 上下文装配：system 拼装 + Think/Respond messages。
Orchestrator / 测试调用这里；loop（think/execute/respond）只消费已拼好的 messages。
"""

from __future__ import annotations
from pathlib import Path
from typing import Any
from a2ui.basic_catalog.provider import BasicCatalog
from a2ui.schema.constants import VERSION_0_9
from a2ui.schema.manager import A2uiSchemaManager
from agent.prompts import RESPOND_MARKDOWN_SYSTEM, THINK_SYSTEM
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


def build_think_system(
    *,
    skills_dir: Path,
    skills_exclude: list[str] | None = None,
    catalog: Any | None = None,
) -> str:
    """Think system = THINK_SYSTEM + skills +（可选）API 分组目录。"""
    parts = [THINK_SYSTEM.strip()]
    skills = load_skills(skills_dir, exclude=skills_exclude or [])
    skills_text = build_skills_prompt(skills).strip()
    if skills_text:
        parts.append(skills_text)
    if catalog is not None:
        catalog_text = format_catalog_for_prompt(catalog).strip()
        if catalog_text:
            parts.append(catalog_text)
    return "\n\n".join(parts)


def build_respond_markdown_system() -> str:
    return RESPOND_MARKDOWN_SYSTEM.strip()


def build_respond_a2ui_system(*, ui_description: str = "") -> str:
    """Respond(A2UI) system：SchemaManager 官方 prompt（含 schema）。"""
    manager = A2uiSchemaManager(
        version=VERSION_0_9,
        catalogs=[BasicCatalog.get_config(version=VERSION_0_9)],
    )
    return manager.generate_system_prompt(
        role_description=(
            "You are a helpful assistant. When the user needs an interactive list "
            "or form, your final output MUST include valid A2UI UI JSON messages."
        ),
        workflow_description=(
            "Emit A2UI messages: createSurface, updateComponents, updateDataModel."
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
    return [*assembled, *turn]


def assemble_respond_markdown(
    *,
    system_prompt: str,
    think_content: str,
) -> list[Message]:
    """Respond(Markdown)：与 A2UI 相同，仅 system + 本轮最后一轮 Think 正文。"""
    body = (think_content or "").strip()
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
    return [
        Message(role=Role.SYSTEM, content=system_prompt),
        Message(role=Role.USER, content=body),
    ]
