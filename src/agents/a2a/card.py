"""Hubloom A2A Agent Card（入站发现用）。"""

from __future__ import annotations

from typing import Any

from a2a.types import (
    AgentCapabilities,
    AgentCard,
    AgentInterface,
    AgentSkill,
)

from agents.a2a.card_polish import polish_card_copy
from agents.agent_log import a2a_log
from mcp_adapter.gateway.catalog import GatewayCatalog, GroupCatalog

_MAX_EXAMPLES = 2


def _skill_from_group(group: GroupCatalog) -> AgentSkill:
    """一个 OpenAPI tag → 一个 AgentSkill（规则草稿）。"""
    examples: list[str] = []
    for tool in group.tools:
        text = (tool.description or tool.name or "").strip()
        if text and text not in examples:
            examples.append(text)
        if len(examples) >= _MAX_EXAMPLES:
            break
    if not examples:
        examples = [f"Help me with {group.tag}"]

    desc = (group.description or group.tag).strip()
    if group.tool_count:
        desc = f"{desc} ({group.tool_count} APIs)"

    return AgentSkill(
        id=group.tag,
        name=group.tag,
        description=desc,
        input_modes=["text/plain"],
        output_modes=["text/plain"],
        tags=["hubloom", "openapi", group.tag],
        examples=examples,
    )


def skills_from_catalog(catalog: GatewayCatalog) -> list[AgentSkill]:
    if not catalog.groups:
        raise ValueError(
            "GatewayCatalog is empty; Swagger/catalog must be ready before building Agent Card"
        )
    skills = [
        _skill_from_group(group)
        for tag in catalog.list_tags()
        if (group := catalog.get_group(tag)) is not None
    ]
    if not skills:
        raise ValueError("no skills generated from GatewayCatalog")
    return skills


def _apply_polish(
    skills: list[AgentSkill],
    polish: dict,
) -> tuple[str, list[AgentSkill]]:
    """把 LLM 文案填回 skills；id/name 不变。"""
    by_id = {item["id"]: item for item in polish["skills"]}
    polished_skills: list[AgentSkill] = []
    for skill in skills:
        item = by_id[skill.id]
        examples = item["examples"] or list(skill.examples)
        polished_skills.append(
            AgentSkill(
                id=skill.id,
                name=skill.name,
                description=item["description"],
                input_modes=list(skill.input_modes),
                output_modes=list(skill.output_modes),
                tags=list(skill.tags),
                examples=examples,
            )
        )
    return polish["agent_description"], polished_skills


def _rule_based_polish(
    skills: list[AgentSkill],
    catalog: GatewayCatalog,
) -> dict[str, Any]:
    """无 OPENAI_API_KEY 时用规则文案，避免启动阶段依赖 .env。"""
    tags = catalog.list_tags()
    if tags:
        summary = f"Hubloom agent with OpenAPI groups: {', '.join(tags)}"
    else:
        summary = "Hubloom agent (configure MCP Swagger to expose skills)"
    return {
        "agent_description": summary,
        "skills": [
            {
                "id": skill.id,
                "description": skill.description,
                "examples": list(skill.examples),
            }
            for skill in skills
        ],
    }


async def build_agent_card(
    public_url: str,
    catalog: GatewayCatalog,
    *,
    openai_api_key: str | None = None,
    openai_model: str | None = None,
    openai_base_url: str | None = None,
) -> AgentCard:
    """根据对外 URL + Swagger catalog 生成 Agent Card（有 Key 时 LLM 润色）。"""
    public_url = public_url.rstrip("/")
    skills = skills_from_catalog(catalog)

    key = (openai_api_key or "").strip()
    if key:
        polish = await polish_card_copy(
            catalog,
            api_key=key,
            model=openai_model,
            base_url=openai_base_url,
        )
    else:
        a2a_log("card polish skipped", reason="openai_api_key not provided")
        polish = _rule_based_polish(skills, catalog)
    description, skills = _apply_polish(skills, polish)

    return AgentCard(
        name="Hubloom",
        description=description,
        version="0.1.0",
        default_input_modes=["text/plain"],
        default_output_modes=["text/plain"],
        capabilities=AgentCapabilities(streaming=True),
        supported_interfaces=[
            AgentInterface(
                protocol_binding="JSONRPC",
                url=public_url,
                protocol_version="1.0",
            )
        ],
        skills=skills,
    )
