"""扫描本地 Skill 目录（仅识别 */SKILL.md）。"""

from __future__ import annotations

import re
from pathlib import Path


def resolve_skills_dir(skills_dir: str | Path | None, *, repo_root: Path) -> Path:
    """相对路径相对仓库根；绝对路径原样使用。默认 ``skills``。"""
    raw = (str(skills_dir).strip() if skills_dir else "") or "skills"
    path = Path(raw)
    if not path.is_absolute():
        path = repo_root / path
    return path.resolve()


def list_skill_md_paths(skills_dir: Path) -> list[Path]:
    """返回 ``skills_dir/*/SKILL.md``（存在的文件）。"""
    if not skills_dir.is_dir():
        return []
    found: list[Path] = []
    for child in sorted(skills_dir.iterdir()):
        if not child.is_dir():
            continue
        skill_md = child / "SKILL.md"
        if skill_md.is_file():
            found.append(skill_md)
    return found


def has_any_skill(skills_dir: Path) -> bool:
    return bool(list_skill_md_paths(skills_dir))


def tag_to_dirname(tag: str) -> str:
    """OpenAPI tag → 安全目录名。"""
    text = (tag or "").strip().lower()
    text = re.sub(r"[^a-z0-9]+", "-", text)
    text = text.strip("-") or "untagged"
    return text[:64]
