"""Playbook 规程模型与 Skill frontmatter 编译（Step 4）。"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Sequence


@dataclass(frozen=True)
class RequireStep:
    """必经步骤：所列工具任一成功执行后视为完成。"""

    id: str
    tools: tuple[str, ...]


@dataclass(frozen=True)
class Playbook:
    """最小可执行规程；空 Playbook = 纯能力环。"""

    forbid_tools: frozenset[str] = field(default_factory=frozenset)
    require_steps: tuple[RequireStep, ...] = ()
    confirm_tools: frozenset[str] = field(default_factory=frozenset)
    sources: tuple[str, ...] = ()

    def is_empty(self) -> bool:
        return (
            not self.forbid_tools
            and not self.require_steps
            and not self.confirm_tools
        )

    def summary_for_prompt(self) -> str:
        if self.is_empty():
            return ""
        lines = ["## Playbook（硬规程，Gate 会拦截）"]
        if self.forbid_tools:
            lines.append(
                "- 禁止工具: " + ", ".join(sorted(self.forbid_tools))
            )
        if self.require_steps:
            for step in self.require_steps:
                tools = ", ".join(step.tools) or "（未绑定工具）"
                lines.append(f"- 必经步骤 `{step.id}`：须先成功调用 [{tools}] 才可 finish")
        if self.confirm_tools:
            lines.append(
                "- 须先 agent_await_confirm 再调用: "
                + ", ".join(sorted(self.confirm_tools))
            )
        if self.sources:
            lines.append("- 来源 Skills: " + ", ".join(self.sources))
        return "\n".join(lines)


@dataclass
class PlaybookProgress:
    """单次 Run 内的规程进度（interactive 挂起时随 Snapshot 保存）。"""

    completed_steps: set[str] = field(default_factory=set)
    confirmed: bool = False
    reject_counts: dict[str, int] = field(default_factory=dict)
    fuse_limit: int = 2

    def mark_tool_success(self, tool_name: str, playbook: Playbook) -> None:
        for step in playbook.require_steps:
            if tool_name in step.tools:
                self.completed_steps.add(step.id)

    def mark_confirmed(self) -> None:
        self.confirmed = True

    def note_reject(self, code: str) -> int:
        n = self.reject_counts.get(code, 0) + 1
        self.reject_counts[code] = n
        return n

    def should_fuse(self, code: str) -> bool:
        return self.reject_counts.get(code, 0) >= self.fuse_limit


def _as_str_list(raw: Any) -> list[str]:
    if raw is None:
        return []
    if isinstance(raw, str):
        return [x.strip() for x in raw.split(",") if x.strip()]
    if isinstance(raw, (list, tuple)):
        out: list[str] = []
        for x in raw:
            s = str(x).strip()
            if s:
                out.append(s)
        return out
    return []


def playbook_from_mapping(
    raw: dict[str, Any] | None,
    *,
    source: str = "",
) -> Playbook:
    """从 frontmatter ``playbook:`` 映射编译。"""
    if not raw or not isinstance(raw, dict):
        return Playbook(sources=(source,) if source else ())

    forbid = frozenset(_as_str_list(raw.get("forbid_tools") or raw.get("forbid")))
    confirm = frozenset(
        _as_str_list(raw.get("confirm_tools") or raw.get("require_confirm"))
    )

    steps_raw = raw.get("require_steps") or raw.get("required_steps") or []
    steps: list[RequireStep] = []
    if isinstance(steps_raw, list):
        for item in steps_raw:
            if isinstance(item, str):
                steps.append(RequireStep(id=item, tools=()))
                continue
            if not isinstance(item, dict):
                continue
            sid = str(item.get("id") or "").strip()
            if not sid:
                continue
            tools = tuple(
                _as_str_list(item.get("tools") or item.get("by_tools") or [])
            )
            steps.append(RequireStep(id=sid, tools=tools))

    return Playbook(
        forbid_tools=forbid,
        require_steps=tuple(steps),
        confirm_tools=confirm,
        sources=(source,) if source else (),
    )


def merge_playbooks(parts: Sequence[Playbook]) -> Playbook:
    forbid: set[str] = set()
    confirm: set[str] = set()
    steps: dict[str, RequireStep] = {}
    sources: list[str] = []
    for p in parts:
        if p.is_empty() and not p.sources:
            continue
        forbid |= set(p.forbid_tools)
        confirm |= set(p.confirm_tools)
        for s in p.require_steps:
            prev = steps.get(s.id)
            if prev is None:
                steps[s.id] = s
            else:
                steps[s.id] = RequireStep(
                    id=s.id, tools=tuple(dict.fromkeys([*prev.tools, *s.tools]))
                )
        sources.extend(p.sources)
    return Playbook(
        forbid_tools=frozenset(forbid),
        require_steps=tuple(steps.values()),
        confirm_tools=frozenset(confirm),
        sources=tuple(dict.fromkeys(sources)),
    )


def compile_playbook_from_skills(skills: Sequence[dict[str, Any]]) -> Playbook:
    """合并各 Skill 的 ``playbook`` 字段（由 skill loader 解析）。"""
    parts: list[Playbook] = []
    for s in skills:
        raw = s.get("playbook")
        name = str(s.get("name") or s.get("id") or "").strip()
        parts.append(playbook_from_mapping(raw if isinstance(raw, dict) else None, source=name))
    return merge_playbooks(parts)
