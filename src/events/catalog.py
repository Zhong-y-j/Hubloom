"""事件目录：真相源为 ``skills/events/*.md`` 分册；YAML 可覆盖。"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from events.models import HubloomEvent

_PLACEHOLDER = re.compile(r"\{([a-zA-Z0-9_.]+)\}")
_SKIP_NAMES = frozenset({"skill.md", "readme.md"})


def resolve_events_skill_dir(
    *,
    skills_dir: str | Path | None = None,
    source_path: str | None = None,
) -> Path:
    """解析 ``<skills_dir>/events``（相对路径相对配置文件所在仓库根）。"""
    text = str(skills_dir or "skills").strip() or "skills"
    path = Path(text)
    if not path.is_absolute():
        if source_path:
            root = Path(source_path).resolve().parents[1]
        else:
            root = Path.cwd()
        path = root / path
    return path / "events"


@dataclass(frozen=True)
class EventTypeConfig:
    type: str
    title: str
    description: str
    # 分册正文（处理规程）；可被 YAML instruction_template 覆盖
    playbook: str
    hint_tags: tuple[str, ...] = ()
    payload_fields: tuple[str, ...] = ()
    playbook_file: str = ""
    skill_id: str = "events"

    @property
    def instruction_template(self) -> str:
        """兼容旧测试/调用方：等同 playbook。"""
        return self.playbook


def _as_str_tuple(value: Any) -> tuple[str, ...]:
    if value is None:
        return ()
    if isinstance(value, str):
        parts = [p.strip() for p in value.split(",") if p.strip()]
        return tuple(parts)
    if isinstance(value, list):
        return tuple(str(x).strip() for x in value if str(x).strip())
    return ()


def _parse_frontmatter_md(path: Path) -> tuple[dict[str, Any], str]:
    text = path.read_text(encoding="utf-8")
    parts = text.split("---", 2)
    if len(parts) < 3:
        return {}, text.strip()
    meta_raw = parts[1]
    body = parts[2].strip()
    try:
        meta = yaml.safe_load(meta_raw) or {}
    except yaml.YAMLError:
        meta = {}
    if not isinstance(meta, dict):
        meta = {}
    return meta, body


def scan_event_playbooks(events_dir: Path | str | None) -> dict[str, dict[str, Any]]:
    """扫描 ``events_dir`` 下除 SKILL.md 外的 ``*.md`` 分册。"""
    if events_dir is None:
        return {}
    root = Path(events_dir)
    if not root.is_dir():
        return {}

    out: dict[str, dict[str, Any]] = {}
    for path in sorted(root.glob("*.md")):
        if path.name.lower() in _SKIP_NAMES:
            continue
        meta, body = _parse_frontmatter_md(path)
        event_type = str(meta.get("event") or "").strip()
        if not event_type:
            continue
        if not body and not str(meta.get("instruction_template") or "").strip():
            continue
        playbook = str(meta.get("instruction_template") or "").strip() or body
        out[event_type] = {
            "title": str(meta.get("title") or event_type).strip() or event_type,
            "description": str(meta.get("description") or "").strip(),
            "playbook": playbook,
            "hint_tags": list(_as_str_tuple(meta.get("hint_tags"))),
            "payload_fields": list(_as_str_tuple(meta.get("payload_fields"))),
            "playbook_file": path.name,
            "skill_id": str(meta.get("skill_id") or "events").strip() or "events",
        }
    return out


def _entry_from_raw(event_type: str, val: dict[str, Any]) -> EventTypeConfig | None:
    title = str(val.get("title") or event_type).strip() or event_type
    desc = str(val.get("description") or "").strip()
    playbook = str(
        val.get("playbook") or val.get("instruction_template") or ""
    ).strip()
    if not playbook:
        return None
    return EventTypeConfig(
        type=event_type,
        title=title,
        description=desc,
        playbook=playbook,
        hint_tags=_as_str_tuple(val.get("hint_tags")),
        payload_fields=_as_str_tuple(val.get("payload_fields")),
        playbook_file=str(val.get("playbook_file") or "").strip(),
        skill_id=str(val.get("skill_id") or "events").strip() or "events",
    )


@dataclass
class EventCatalog:
    """事件类型目录；未知 type 在查找时失败。"""

    _entries: dict[str, EventTypeConfig] = field(default_factory=dict)
    events_dir: str | None = None

    @classmethod
    def load(
        cls,
        *,
        events_dir: Path | str | None = None,
        config_catalog: dict[str, Any] | None = None,
    ) -> EventCatalog:
        """Skill 分册为真相源；``config_catalog`` 同名覆盖/可追加纯 YAML 类型。"""
        merged: dict[str, Any] = scan_event_playbooks(events_dir)
        raw = config_catalog or {}
        if isinstance(raw, dict):
            for key, val in raw.items():
                k = str(key).strip()
                if not k or not isinstance(val, dict):
                    continue
                base = dict(merged.get(k) or {})
                # YAML 里 instruction_template → playbook
                overlay = dict(val)
                if "instruction_template" in overlay and "playbook" not in overlay:
                    overlay["playbook"] = overlay.get("instruction_template")
                base.update(overlay)
                merged[k] = base

        entries: dict[str, EventTypeConfig] = {}
        for key, val in merged.items():
            if not isinstance(val, dict):
                continue
            cfg = _entry_from_raw(key, val)
            if cfg is not None:
                entries[key] = cfg
        dir_str = str(Path(events_dir).resolve()) if events_dir else None
        return cls(_entries=entries, events_dir=dir_str)

    @classmethod
    def from_defaults_and_config(
        cls,
        config_catalog: dict[str, Any] | None = None,
        *,
        events_dir: Path | str | None = None,
    ) -> EventCatalog:
        """兼容旧名；未传 ``events_dir`` 时仅用 YAML（测试可自建临时目录）。"""
        return cls.load(events_dir=events_dir, config_catalog=config_catalog)

    def get(self, event_type: str) -> EventTypeConfig:
        key = (event_type or "").strip()
        entry = self._entries.get(key)
        if entry is None:
            known = ", ".join(self.types()) or "（无）"
            raise KeyError(f"未配置的事件类型: {key!r}；当前支持: {known}")
        return entry

    def types(self) -> list[str]:
        return sorted(self._entries.keys())

    def list_types(self) -> list[dict[str, Any]]:
        """供 ``GET /v1/events/types``。"""
        rows: list[dict[str, Any]] = []
        for key in self.types():
            e = self._entries[key]
            rows.append(
                {
                    "type": e.type,
                    "title": e.title,
                    "description": e.description,
                    "payload_fields": list(e.payload_fields),
                    "hint_tags": list(e.hint_tags),
                    "playbook_file": e.playbook_file,
                    "skill_id": e.skill_id,
                }
            )
        return rows


def _lookup_placeholder(
    key: str,
    *,
    event: HubloomEvent,
    entry: EventTypeConfig,
) -> str:
    if key == "description":
        return entry.description or "未提供"
    if key == "title":
        return entry.title or event.type
    if key == "type":
        return event.type
    if key == "event_id":
        return event.event_id
    if key.startswith("payload."):
        field = key[len("payload.") :]
        val = event.payload.get(field)
        if val is None or (isinstance(val, str) and not val.strip()):
            return "未提供"
        return str(val)
    return "未提供"


def apply_template(
    template: str,
    *,
    event: HubloomEvent,
    entry: EventTypeConfig,
) -> str:
    def repl(match: re.Match[str]) -> str:
        return _lookup_placeholder(match.group(1), event=event, entry=entry)

    return _PLACEHOLDER.sub(repl, template or "")


def _format_payload_block(event: HubloomEvent, entry: EventTypeConfig) -> str:
    keys = list(entry.payload_fields) if entry.payload_fields else []
    if not keys:
        keys = [str(k) for k in event.payload.keys()]
    if not keys:
        return "- （无 payload）"
    lines: list[str] = []
    for key in keys:
        val = event.payload.get(key)
        if val is None or (isinstance(val, str) and not str(val).strip()):
            # 也展示规程里提到的字段占位
            if key in entry.payload_fields or key in event.payload:
                lines.append(f"- {key}：未提供")
            continue
        lines.append(f"- {key}：{val}")
    # 补充 payload 里有、但 fields 未列出的键
    for key, val in event.payload.items():
        if key in keys:
            continue
        if val is None or (isinstance(val, str) and not str(val).strip()):
            continue
        lines.append(f"- {key}：{val}")
    return "\n".join(lines) if lines else "- （无 payload）"


def render_event_trigger(
    event: HubloomEvent,
    entry: EventTypeConfig,
) -> str:
    """拼进会话：事件字段 + 已注入的分册规程（避免模型未读 skill 就总结）。"""
    if event.instruction:
        playbook = event.instruction.strip()
    else:
        playbook = apply_template(entry.playbook, event=event, entry=entry).strip()

    lines = [
        "本轮由业务事件触发（非用户闲聊）。",
        "请严格按下方【事件处理规程】逐步执行；禁止跳过规程直接总结收工。",
        f"总则可 read_skill(skill={entry.skill_id!r})；本轮对应分册正文已注入，勿以未读为由空转。",
        "",
        f"【事件 · {event.type} · {entry.title}】",
    ]
    if entry.description:
        lines.append(f"含义：{entry.description}")
    lines.append("业务数据：")
    lines.append(_format_payload_block(event, entry))
    lines.append("")
    src = entry.playbook_file or event.type
    lines.append(f"【事件处理规程 · {src}】")
    lines.append(playbook)
    if entry.hint_tags:
        lines.append("")
        lines.append("建议优先查看 API 分组：" + "、".join(entry.hint_tags))
    if event.occurred_at:
        lines.append(f"occurred_at: {event.occurred_at}")
    lines.append(f"event_id: {event.event_id}")
    return "\n".join(lines).strip() + "\n"
