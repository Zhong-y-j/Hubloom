"""Skill 元工具：按需读取 SKILL.md 正文（不执行业务）。

与业务 API 元工具 list_api / call_api 分工：
- system 里已有 Skills 名片（name + description）
- 需要细则时再 read_skill；读完按正文去 call_api / 交 Respond
- 本工具不做 call_skill
"""

from __future__ import annotations

import contextvars
from pathlib import Path
from typing import Any, Sequence

from skill.load import load_skills
from tools.base import BaseTool

# 本轮已成功加载过的 skill id（目录名）；每轮开始需 clear_read_skill_turn_state()
_loaded_skill_ids: contextvars.ContextVar[set[str] | None] = contextvars.ContextVar(
    "loaded_skill_ids", default=None
)


def clear_read_skill_turn_state() -> None:
    """每轮用户消息进入 run_stream 时调用，防止跨轮误伤、本轮重复读取。"""
    _loaded_skill_ids.set(set())


def _turn_loaded() -> set[str]:
    cur = _loaded_skill_ids.get()
    if cur is None:
        cur = set()
        _loaded_skill_ids.set(cur)
    return cur


def _norm(s: str) -> str:
    return (s or "").strip().lower()


def resolve_skill(
    skills: Sequence[dict[str, Any]], key: str
) -> dict[str, Any] | None:
    """按目录 id 或 frontmatter name 解析；id 优先。"""
    raw = (key or "").strip()
    if not raw:
        return None
    needle = _norm(raw)

    for s in skills:
        if _norm(str(s.get("id") or "")) == needle:
            return s
    for s in skills:
        if _norm(str(s.get("name") or "")) == needle:
            return s
    return None


def available_skill_labels(skills: Sequence[dict[str, Any]]) -> str:
    parts: list[str] = []
    for s in skills:
        sid = str(s.get("id") or "").strip() or "?"
        name = str(s.get("name") or "").strip() or sid
        if name == sid:
            parts.append(sid)
        else:
            parts.append(f"{sid} (name={name})")
    return ", ".join(parts) if parts else "（无）"


class ReadSkillTool(BaseTool):
    """读取指定 Skill 的 SKILL.md 正文。"""

    name = "read_skill"
    description = (
        "读取指定 Skill 的 SKILL.md 正文（操作细则）。"
        "仅当「可用 Skills」名片与当前任务匹配、且正文尚未出现在本轮上下文时调用。"
        "参数 skill 为目录 id（推荐，如 account-access）或 frontmatter name。"
        "同一 Skill 每轮最多成功读取一次；读完后按正文执行，禁止重复读取。"
        "本工具不执行业务，不能代替 list_api / call_api。"
    )
    parameters = {
        "type": "object",
        "properties": {
            "skill": {
                "type": "string",
                "description": "Skill 目录 id 或 name，例如 account-access",
            },
        },
        "required": ["skill"],
    }

    def __init__(
        self,
        *,
        skills_dir: str | Path,
        skills_exclude: Sequence[str] | None = None,
        skills: Sequence[dict[str, Any]] | None = None,
    ) -> None:
        self._skills_dir = Path(skills_dir)
        self._skills_exclude = list(skills_exclude or [])
        # 启动时传入可避免每次读盘；为 None 则首次 execute 时 load
        self._skills: list[dict[str, Any]] | None = (
            list(skills) if skills is not None else None
        )

    def _catalog(self) -> list[dict[str, Any]]:
        if self._skills is None:
            self._skills = load_skills(
                self._skills_dir, exclude=self._skills_exclude
            )
        return self._skills

    async def execute(self, skill: str = "", **_: Any) -> str:
        key = (skill or "").strip()
        if not key:
            return "错误：skill 不能为空。请传入目录 id 或 name（见「可用 Skills」）。"

        catalog = self._catalog()
        if not catalog:
            return "错误：当前未配置任何 Skill（skills 目录为空或均被 exclude）。"

        hit = resolve_skill(catalog, key)
        if hit is None:
            return (
                f"错误：未知 skill: {key!r}。"
                f"可用：{available_skill_labels(catalog)}"
            )

        sid = str(hit.get("id") or "").strip() or key
        loaded = _turn_loaded()
        if sid in loaded:
            return (
                f"skill {sid} 已在本轮加载，请根据上文正文执行，"
                f"勿重复 read_skill。"
            )

        body = str(hit.get("body") or "").strip()
        name = str(hit.get("name") or "").strip() or sid
        if not body:
            return f"错误：skill {sid} 的 SKILL.md 正文为空。"

        loaded.add(sid)
        title = name if name == sid else f"{name} (id={sid})"
        return f"# skill: {title}\n\n{body}"


def build_skill_tools(
    *,
    skills_dir: str | Path,
    skills_exclude: Sequence[str] | None = None,
) -> list[BaseTool]:
    """若目录下有 Skill 则注册 read_skill，否则返回空列表。"""
    skills = load_skills(skills_dir, exclude=skills_exclude)
    if not skills:
        return []
    return [
        ReadSkillTool(
            skills_dir=skills_dir,
            skills_exclude=skills_exclude,
            skills=skills,
        )
    ]
