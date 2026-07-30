from __future__ import annotations

from pathlib import Path
from typing import Any, Sequence

import yaml


def load_skills(
    skills_dir: str | Path,
    *,
    exclude: Sequence[str] | None = None,
) -> list[dict[str, Any]]:
    """扫描 ``skills_dir/*/SKILL.md``，读出 name / description / body / playbook。

    ``exclude`` 按**目录名**黑名单过滤（如 ``a2ui``），不是 frontmatter name。
    ``playbook`` 可选，供 Agent Gate 编译（见 agent.policy）。
    """
    root = Path(skills_dir)
    if not root.is_dir():
        return []

    blocked = {str(x).strip() for x in (exclude or []) if str(x).strip()}
    skills: list[dict[str, Any]] = []

    for folder in sorted(root.iterdir()):
        if not folder.is_dir() or folder.name.startswith("."):
            continue
        if folder.name in blocked:
            continue

        path = folder / "SKILL.md"
        if not path.is_file():
            continue

        text = path.read_text(encoding="utf-8")
        parts = text.split("---", 2)
        if len(parts) < 3:
            continue
        _, meta, body = parts

        meta_dict: dict[str, Any] = {}
        try:
            loaded = yaml.safe_load(meta) or {}
            if isinstance(loaded, dict):
                meta_dict = loaded
        except Exception:
            meta_dict = _parse_meta_fallback(meta)

        name = str(meta_dict.get("name") or "").strip() or folder.name
        desc = meta_dict.get("description")
        if isinstance(desc, str):
            description = " ".join(desc.split())
        else:
            description = ""

        playbook = meta_dict.get("playbook")
        if playbook is not None and not isinstance(playbook, dict):
            playbook = None

        skills.append(
            {
                "name": name,
                "description": description,
                "body": body.strip(),
                "path": path,
                "id": folder.name,
                "playbook": playbook,
            }
        )
    return skills


def _parse_meta_fallback(meta: str) -> dict[str, Any]:
    """YAML 失败时退回旧行解析（仅 name / description）。"""
    name = ""
    desc_lines: list[str] = []
    in_desc = False
    for line in meta.splitlines():
        if line.startswith("name:"):
            name = line.split(":", 1)[1].strip()
            in_desc = False
        elif line.startswith("description:"):
            first = line.split(":", 1)[1].strip().strip(">")
            desc_lines = [first] if first else []
            in_desc = True
        elif in_desc and line.strip():
            desc_lines.append(line.strip())
        elif in_desc and not line.strip():
            in_desc = False
    return {
        "name": name,
        "description": " ".join(desc_lines).strip(),
    }


def build_skills_prompt(skills: Sequence[dict[str, Any]]) -> str:
    """只把名片（name + description）拼进 prompt，不放 body。"""
    if not skills:
        return ""
    lines = [
        "【可用 Skills】",
        "以下为技能名片（name + description）。需要细则时调用工具 read_skill(skill=name)，"
        "再按返回的 SKILL.md 正文执行；同一 skill 每轮只读一次。",
    ]
    for s in skills:
        name = (s.get("name") or "").strip() or "?"
        desc = (s.get("description") or "").strip() or "（无描述）"
        lines.append(f"- {name}: {desc}")
    return "\n".join(lines)
