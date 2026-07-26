"""事件幂等：同一 event_id 只真正跑一次 Agent。"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class EventDispatchResult:
    event_id: str
    session_id: str
    type: str
    ok: bool
    duplicate: bool = False
    summary: str = ""
    error: str | None = None
    turn_count: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "event_id": self.event_id,
            "session_id": self.session_id,
            "type": self.type,
            "ok": self.ok,
            "duplicate": self.duplicate,
            "summary": self.summary,
            "error": self.error,
            "turn_count": self.turn_count,
        }


@dataclass
class IdempotencyStore:
    """进程内幂等表（MVP）。

    并发由 ``EventDispatcher`` 的 claim 锁串行化，本表不做独立加锁。
    """

    _done: dict[str, EventDispatchResult] = field(default_factory=dict)

    def get(self, event_id: str) -> EventDispatchResult | None:
        return self._done.get(event_id)

    def put(self, result: EventDispatchResult) -> None:
        self._done[result.event_id] = result
