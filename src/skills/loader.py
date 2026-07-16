"""扫描 ``skills_dir/*/SKILL.md``，按黑名单过滤后拼成 Markdown prompt。

约定：
- skill id = 子目录名（如 ``a2ui``）
- 每个子目录需有 ``SKILL.md`` 才会被加载
- ``skills_exclude`` 匹配目录名（大小写不敏感）
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Sequence


@dataclass(frozen=True)
class LoadedSkill:
    """单个已加载的 Skill。"""

    skill_id: str
    path: Path
    body: str


def resolve_skills_root(
    skills_dir: str | Path = "skills",
    *,
    project_root: str | Path | None = None,
) -> Path:
    """解析 skills 根目录。相对路径相对 ``project_root``（默认 cwd）。"""
    path = Path(skills_dir)
    if path.is_absolute():
        return path
    root = Path(project_root) if project_root is not None else Path.cwd()
    return (root / path).resolve()


def _strip_frontmatter(text: str) -> str:
    """去掉 YAML frontmatter（``---`` ... ``---``），保留正文。"""
    if not text.startswith("---"):
        return text
    # 允许首行 ``---`` 后带空白
    first_nl = text.find("\n")
    if first_nl < 0:
        return text
    end = text.find("\n---", first_nl + 1)
    if end < 0:
        return text
    rest = text[end + len("\n---") :]
    if rest.startswith("\n"):
        rest = rest[1:]
    return rest


def _normalize_exclude(exclude: Sequence[str] | None) -> set[str]:
    if not exclude:
        return set()
    return {item.strip().lower() for item in exclude if item and str(item).strip()}


def load_skills(
    skills_dir: str | Path = "skills",
    *,
    exclude: Sequence[str] | None = None,
    project_root: str | Path | None = None,
) -> list[LoadedSkill]:
    """扫描并加载 skills；按 ``skill_id`` 字典序排序。"""
    root = resolve_skills_root(skills_dir, project_root=project_root)
    if not root.is_dir():
        return []

    blocked = _normalize_exclude(exclude)
    loaded: list[LoadedSkill] = []

    for child in sorted(root.iterdir(), key=lambda p: p.name.lower()):
        if not child.is_dir() or child.name.startswith("."):
            continue
        skill_id = child.name
        if skill_id.lower() in blocked:
            continue
        skill_file = child / "SKILL.md"
        if not skill_file.is_file():
            continue
        raw = skill_file.read_text(encoding="utf-8")
        body = _strip_frontmatter(raw).strip()
        if not body:
            continue
        loaded.append(LoadedSkill(skill_id=skill_id, path=skill_file, body=body))

    return loaded


def format_skills_prompt(skills: Sequence[LoadedSkill]) -> str:
    """将已加载 skills 拼成 Markdown 片段；空列表返回空字符串。"""
    if not skills:
        return ""

    parts: list[str] = ["# Agent Skills", ""]
    for skill in skills:
        parts.append(f"## Skill: `{skill.skill_id}`")
        parts.append("")
        parts.append(skill.body)
        parts.append("")
        parts.append("---")
        parts.append("")

    while parts and parts[-1] in ("", "---"):
        parts.pop()
    return "\n".join(parts).strip() + "\n"


def load_skills_prompt(
    skills_dir: str | Path = "skills",
    *,
    exclude: Sequence[str] | None = None,
    project_root: str | Path | None = None,
) -> str:
    """将已加载 skills 拼成可注入 system prompt 的 Markdown 片段。

    无可用 skill 时返回空字符串。
    """
    return format_skills_prompt(
        load_skills(skills_dir, exclude=exclude, project_root=project_root)
    )
