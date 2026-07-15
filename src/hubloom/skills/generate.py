"""根据 GatewayCatalog 用 LLM 生成并写入 SKILL.md（仅正文文件）。"""

from __future__ import annotations

import re
from pathlib import Path
from typing import TYPE_CHECKING

from agents.agent_log import cortex_log, clip
from core.factory import create_llm
from core.models import Message, Role
from hubloom.skills.discover import (
    has_any_skill,
    list_skill_md_paths,
    resolve_skills_dir,
    tag_to_dirname,
)
from mcp_adapter.gateway.catalog import GatewayCatalog, GroupCatalog

if TYPE_CHECKING:
    from core.provider import LLMProvider

_MAX_OPS = 8

_SYSTEM = """你是 Hubloom Agent Skill 作者。根据给定的 OpenAPI tag 分组，写一份 SKILL.md。
硬性规则：
1. 输出必须是完整 Markdown，开头是 YAML frontmatter（--- 包裹），不要其它解释或代码围栏。
2. frontmatter 必须含：
   name: <与输入 tag_id 相同，或等价的 kebab-case>
   description: <一行，说明做什么 + 何时用 + 明确不要做什么；第三人称>
3. 正文用中文，包含这些小节（可用二级标题）：
   - 何时使用
   - 何时不要用
   - 操作流程（简短步骤）
   - 工具绑定（必须写明只允许 MCP OpenAPI tag 为输入的 tag_id）
   - 示例话术（1～2 个）
   - 输出要求
4. 禁止编造输入里没有的 API 名称；可概括「通过 list_tools / call_tool 调用该 tag 下接口」。
5. 不要生成 references/scripts/assets 说明以外的内容要求。"""


def _group_payload(group: GroupCatalog) -> dict:
    ops = []
    for tool in group.tools[:_MAX_OPS]:
        ops.append(
            {
                "name": tool.name,
                "method": tool.method,
                "path": tool.path,
                "summary": (tool.description or tool.name).strip(),
            }
        )
    return {
        "tag_id": group.tag,
        "raw_description": group.description,
        "api_count": group.tool_count,
        "operations": ops,
    }


def _rule_based_skill_md(group: GroupCatalog) -> str:
    tag = group.tag
    desc = (group.description or tag).strip()
    op_lines = "\n".join(
        f"- `{t.name}` ({t.method} {t.path})：{(t.description or '').strip() or t.name}"
        for t in group.tools[:_MAX_OPS]
    )
    description = (
        f"处理 OpenAPI 分组「{tag}」相关业务（{group.tool_count} 个接口）：{desc}。"
        f"用户意图属于该分组时使用；不要用于其它 tag。"
    )
    return f"""---
name: {tag_to_dirname(tag)}
description: >-
  {description}
---

# {tag}

## 何时使用

- 用户需求落在「{desc}」范围内
- 需要调用本分组下的业务接口

## 何时不要用

- 需求属于其它 OpenAPI tag
- 纯闲聊、无需调 API

## 操作流程

1. 确认用户意图与必要参数
2. 使用 MCP：`list_tools(tag="{tag}")` 查看参数
3. 使用 `call_tool` 调用具体接口
4. 用自然语言汇总结果，勿编造数据

## 工具绑定

本 Skill **只允许** OpenAPI tag：`{tag}`。

相关接口摘要：

{op_lines or "- （无工具列表）"}

## 示例话术

用户：帮我用「{tag}」相关能力办一件事。

做法：确认意图 → list_tools → call_tool → 汇总答复。

## 输出要求

- 中文、简洁；关键 ID / 状态写清楚
- 接口失败时如实说明，不要假装成功
"""


def _strip_fences(text: str) -> str:
    text = (text or "").strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:markdown|md|yaml)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
    return text.strip()


def _looks_like_skill_md(text: str, tag: str) -> bool:
    if not text.startswith("---"):
        return False
    lower = text.lower()
    if "description:" not in lower:
        return False
    # 正文应提到该 tag（绑定）
    if tag.lower() not in lower and tag_to_dirname(tag) not in lower:
        return False
    return True


async def _llm_skill_md(llm: LLMProvider, group: GroupCatalog) -> str:
    import json

    payload = _group_payload(group)
    user = (
        "请为以下 OpenAPI 分组生成 SKILL.md：\n"
        + json.dumps(payload, ensure_ascii=False, indent=2)
    )
    out = await llm.generate(
        [
            Message(role=Role.SYSTEM, content=_SYSTEM),
            Message(role=Role.USER, content=user),
        ]
    )
    content = _strip_fences(getattr(out, "content", None) or "")
    if not _looks_like_skill_md(content, group.tag):
        raise ValueError("LLM skill output failed validation")
    return content


async def generate_skill_md_for_group(
    group: GroupCatalog,
    *,
    llm: LLMProvider | None = None,
) -> str:
    """生成单个 tag 的 SKILL.md 文本；LLM 失败则规则兜底。"""
    if llm is not None:
        try:
            return await _llm_skill_md(llm, group)
        except Exception as exc:
            cortex_log(
                "skill generate llm failed, using rule template",
                tag=group.tag,
                error=type(exc).__name__,
                detail=clip(str(exc), 120),
            )
    return _rule_based_skill_md(group)


async def ensure_skills_from_catalog(
    catalog: GatewayCatalog,
    *,
    skills_dir: str | Path | None = None,
    repo_root: Path,
    api_key: str | None = None,
    model: str | None = None,
    base_url: str | None = None,
    use_llm: bool = True,
) -> dict[str, int | str]:
    """若目录下已有任意 SKILL.md 则跳过；否则按 tag 生成并写入。

    Returns:
        摘要：skipped | written | failed | skills_dir
    """
    root = resolve_skills_dir(skills_dir, repo_root=repo_root)
    if has_any_skill(root):
        existing = len(list_skill_md_paths(root))
        cortex_log(
            "skills already present, skip generate",
            skills_dir=str(root),
            existing=existing,
        )
        return {
            "status": "skipped",
            "skills_dir": str(root),
            "existing": existing,
            "written": 0,
            "failed": 0,
        }

    root.mkdir(parents=True, exist_ok=True)
    llm = None
    if use_llm and (api_key or "").strip():
        llm = create_llm(api_key=api_key, model=model, base_url=base_url)

    written = 0
    failed = 0
    tags = catalog.list_tags()
    cortex_log(
        "skills generate start",
        skills_dir=str(root),
        tag_count=len(tags),
        use_llm=llm is not None,
    )
    for tag in tags:
        group = catalog.get_group(tag)
        if group is None:
            continue
        dirname = tag_to_dirname(tag)
        dest_dir = root / dirname
        dest = dest_dir / "SKILL.md"
        try:
            text = await generate_skill_md_for_group(group, llm=llm)
            dest_dir.mkdir(parents=True, exist_ok=True)
            dest.write_text(text if text.endswith("\n") else text + "\n", encoding="utf-8")
            written += 1
            cortex_log("skill written", tag=tag, path=str(dest))
        except Exception as exc:
            failed += 1
            cortex_log(
                "skill write failed",
                tag=tag,
                error=type(exc).__name__,
                detail=clip(str(exc), 120),
            )

    cortex_log(
        "skills generate done",
        skills_dir=str(root),
        written=written,
        failed=failed,
    )
    return {
        "status": "generated",
        "skills_dir": str(root),
        "written": written,
        "failed": failed,
        "existing": 0,
    }
