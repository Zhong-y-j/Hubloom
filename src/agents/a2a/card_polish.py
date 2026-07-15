"""用一次 LLM 调用润色 Agent Card 文案（不改 skill id）。"""

from __future__ import annotations

import json
import re
from typing import Any

from core.factory import create_llm
from core.models import Message, Role
from mcp_adapter.gateway.catalog import GatewayCatalog

_MAX_OPS_PER_TAG = 5

_SYSTEM = """你是 API 产品文案助手。根据给定的 OpenAPI tag 分组，生成 A2A Agent Card 文案。
硬性规则：
1. 只能使用输入里出现的 tag id，禁止编造新 tag 或新接口能力。
2. 输出必须是合法 JSON，不要 markdown 代码块。
3. JSON 形状：
{
  "agent_description": "一句话总述该 Agent 能办的业务（中文或英文，简洁）",
  "skills": [
    {
      "id": "与输入 tag 完全一致",
      "description": "该分组能力的口语化说明（1-2 句）",
      "examples": ["自然语言示例提问1", "自然语言示例提问2"]
    }
  ]
}
4. skills 必须覆盖输入中的每一个 tag，且 id 一一对应。
5. examples 要像用户会问的话，不要照抄技术 summary。"""


def _catalog_payload(catalog: GatewayCatalog) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for tag in catalog.list_tags():
        group = catalog.get_group(tag)
        if group is None:
            continue
        ops = []
        for tool in group.tools[:_MAX_OPS_PER_TAG]:
            ops.append(
                {
                    "name": tool.name,
                    "summary": (tool.description or tool.name).strip(),
                }
            )
        items.append(
            {
                "id": group.tag,
                "raw_description": group.description,
                "api_count": group.tool_count,
                "operations": ops,
            }
        )
    return items


def _extract_json(text: str) -> dict[str, Any]:
    text = (text or "").strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
    return json.loads(text)


def _validate_polish(data: dict[str, Any], catalog: GatewayCatalog) -> dict[str, Any]:
    allowed = set(catalog.list_tags())
    agent_description = str(data.get("agent_description") or "").strip()
    if not agent_description:
        raise ValueError("LLM polish missing agent_description")

    raw_skills = data.get("skills")
    if not isinstance(raw_skills, list):
        raise ValueError("LLM polish skills must be a list")

    by_id: dict[str, dict[str, Any]] = {}
    for item in raw_skills:
        if not isinstance(item, dict):
            continue
        sid = str(item.get("id") or "").strip()
        if sid not in allowed:
            continue
        desc = str(item.get("description") or "").strip()
        examples = item.get("examples") or []
        if not isinstance(examples, list):
            examples = []
        examples = [str(x).strip() for x in examples if str(x).strip()][:2]
        if not desc:
            continue
        by_id[sid] = {
            "id": sid,
            "description": desc,
            "examples": examples,
        }

    missing = allowed - set(by_id)
    if missing:
        raise ValueError(f"LLM polish missing skills for tags: {sorted(missing)}")

    return {
        "agent_description": agent_description,
        "skills": [by_id[tag] for tag in catalog.list_tags()],
    }


async def polish_card_copy(catalog: GatewayCatalog) -> dict[str, Any]:
    """一次 LLM 调用，返回校验后的润色结果。"""
    payload = _catalog_payload(catalog)
    user_text = "请基于以下 OpenAPI 能力分组生成 Agent Card 文案：\n" + json.dumps(
        payload, ensure_ascii=False, indent=2
    )

    llm = create_llm()
    output = await llm.generate(
        [
            Message(role=Role.SYSTEM, content=_SYSTEM),
            Message(role=Role.USER, content=user_text),
        ]
    )
    content = (output.content or "").strip()
    data = _extract_json(content)
    return _validate_polish(data, catalog)
