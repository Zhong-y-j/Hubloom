"""文件系统 Skills：扫描 ``skills/*/SKILL.md``，拼成可注入的 prompt 片段。"""

from .loader import (
    LoadedSkill,
    format_skills_prompt,
    load_skills,
    load_skills_prompt,
    resolve_skills_root,
)

__all__ = [
    "LoadedSkill",
    "format_skills_prompt",
    "load_skills",
    "load_skills_prompt",
    "resolve_skills_root",
]
