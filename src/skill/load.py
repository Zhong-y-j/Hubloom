"""扫描 ``SKILL.md``，把技能名片注入 system prompt。"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Sequence


def load_skills(
    skills_dir: str | Path,
    *,
    exclude: Sequence[str] | None = None,
) -> list[dict[str, Any]]:
    """扫描 ``skills_dir/*/SKILL.md``，读出 name / description / body。

    ``exclude`` 按**目录名**黑名单过滤（如 ``a2ui``），不是 frontmatter name。
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

        skills.append(
            {
                "name": name or folder.name,
                "description": " ".join(desc_lines).strip(),
                "body": body.strip(),
                "path": path,
                "id": folder.name,
            }
        )
    return skills


def build_skills_prompt(skills: Sequence[dict[str, Any]]) -> str:
    """只把名片（name + description）拼进 prompt，不放 body。"""
    if not skills:
        return ""
    lines = [
        "【可用 Skills】",
        "以下为技能名片；需要时按技能约定执行（详细步骤在对应 SKILL.md 正文）。",
    ]
    for s in skills:
        name = (s.get("name") or "").strip() or "?"
        desc = (s.get("description") or "").strip() or "（无描述）"
        lines.append(f"- {name}: {desc}")
    return "\n".join(lines)
