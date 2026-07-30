"""Session 端口：pending / awaiting；存储实现见 RedisSessionStore。"""

from __future__ import annotations

import secrets
import time
from dataclasses import dataclass, field
from typing import Any, Literal, Protocol

from core.models import Message

from agent.evidence import EvidenceJournal
from agent.policy import PlaybookProgress

WaitKind = Literal["ask", "await_confirm"]
SessionStatus = Literal["idle", "running", "awaiting_user"]


def new_await_token() -> str:
    return secrets.token_hex(8)


@dataclass
class PendingState:
    """turn_based：跨 Run 交班意图（不存长期密钥）。"""

    kind: WaitKind
    prompt: str
    slots: list[str] = field(default_factory=list)
    payload: dict[str, Any] = field(default_factory=dict)
    intent: str = ""
    from_run_id: str = ""
    evidence_ids: list[str] = field(default_factory=list)

    def summary_for_prompt(self) -> str:
        slots = ", ".join(self.slots) if self.slots else "（无）"
        intent = self.intent.strip() or "（未标）"
        return (
            "## Pending（跨轮待办）\n"
            f"- kind: {self.kind}\n"
            f"- prompt: {self.prompt}\n"
            f"- slots: {slots}\n"
            f"- intent: {intent}\n"
            "请结合用户本轮回复继续：缺参再 ask，齐了就 act，办完 finish。"
        )


@dataclass
class AwaitingSnapshot:
    """interactive：同一 Run 挂起快照（Redis SessionStore 持久化）。"""

    run_id: str
    await_token: str
    kind: WaitKind
    prompt: str
    slots: list[str]
    payload: dict[str, Any]
    journal: EvidenceJournal
    turn_messages: list[Message]
    rounds: int
    tool_calls_n: int
    tool_errors_n: int
    started: float
    system_before: str
    system_after: str
    parse_retries: int
    max_rounds: int
    progress: PlaybookProgress | None = None
    created_at: float = field(default_factory=time.time)


@dataclass
class SessionRecord:
    session_id: str
    status: SessionStatus = "idle"
    pending: PendingState | None = None
    awaiting: AwaitingSnapshot | None = None
    active_run_id: str | None = None


class SessionStore(Protocol):
    def get(self, session_id: str) -> SessionRecord | None: ...

    def put(self, record: SessionRecord) -> None: ...

    def delete(self, session_id: str) -> None: ...


def ensure_record(store: SessionStore, session_id: str) -> SessionRecord:
    rec = store.get(session_id)
    if rec is None:
        rec = SessionRecord(session_id=session_id)
        store.put(rec)
    return rec


def cancel_awaiting(
    store: SessionStore,
    session_id: str,
    *,
    run_id: str | None = None,
) -> bool:
    """显式取消 interactive 挂起；返回是否清掉了 awaiting。"""
    rec = store.get(session_id)
    if rec is None or rec.awaiting is None:
        return False
    if run_id is not None and rec.awaiting.run_id != run_id:
        return False
    rec.awaiting = None
    rec.status = "idle"
    rec.active_run_id = None
    store.put(rec)
    return True
