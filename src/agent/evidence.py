"""Evidence Journal：观察入账；Assemble 只带摘要（Step 2）。"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import Any, Literal

EvidenceKind = Literal[
    "observation",
    "ask",
    "await_confirm",
    "finish",
    "parse_reject",
    "policy_reject",
]


def _new_run_id() -> str:
    return uuid.uuid4().hex[:12]


@dataclass
class EvidenceEntry:
    """一条证据；``id`` 可供 ``finish(cites=…)`` 引用。"""

    id: str
    step: int
    kind: EvidenceKind
    summary: str
    tool_name: str = ""
    call_id: str = ""
    is_error: bool = False
    detail: str = ""


@dataclass
class EvidenceJournal:
    """单次 Run 的证据账（进程内；外置挂起态是后续 Step）。"""

    run_id: str = field(default_factory=_new_run_id)
    entries: list[EvidenceEntry] = field(default_factory=list)
    _seq: int = field(default=0, repr=False)

    def append(
        self,
        *,
        step: int,
        kind: EvidenceKind,
        summary: str,
        tool_name: str = "",
        call_id: str = "",
        is_error: bool = False,
        detail: str = "",
    ) -> EvidenceEntry:
        self._seq += 1
        entry = EvidenceEntry(
            id=f"{self.run_id}:{self._seq}",
            step=step,
            kind=kind,
            summary=(summary or "").strip() or "(empty)",
            tool_name=tool_name or "",
            call_id=call_id or "",
            is_error=is_error,
            detail=(detail or "").strip(),
        )
        self.entries.append(entry)
        return entry

    def ids(self) -> list[str]:
        return [e.id for e in self.entries]

    def summary_for_prompt(
        self,
        *,
        max_entries: int = 16,
        max_chars: int = 2_400,
        preview_chars: int = 180,
    ) -> str:
        """给 Assemble 的短摘要（全量 detail 不灌模型）。"""
        if not self.entries:
            return ""
        rows = self.entries[-max_entries:]
        lines = [f"## Evidence Journal (run={self.run_id})", "近期观察（可 cite id）："]
        used = sum(len(x) for x in lines) + len(lines)
        for e in rows:
            flag = " ERR" if e.is_error else ""
            tool = f" tool={e.tool_name}" if e.tool_name else ""
            preview = e.summary
            if len(preview) > preview_chars:
                preview = preview[: preview_chars - 1] + "…"
            line = f"- [{e.id}] step={e.step} {e.kind}{flag}{tool}: {preview}"
            if used + len(line) + 1 > max_chars:
                lines.append("- …（更早条目已裁剪）")
                break
            lines.append(line)
            used += len(line) + 1
        return "\n".join(lines)

    def to_debug_dict(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "entries": [
                {
                    "id": e.id,
                    "step": e.step,
                    "kind": e.kind,
                    "summary": e.summary,
                    "tool_name": e.tool_name,
                    "call_id": e.call_id,
                    "is_error": e.is_error,
                }
                for e in self.entries
            ],
        }
