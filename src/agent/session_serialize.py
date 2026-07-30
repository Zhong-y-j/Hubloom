"""SessionRecord ↔ JSON（供 Redis 持久化挂起 / pending）。"""

from __future__ import annotations

from typing import Any

from core.models import Message, Role, ToolCall

from agent.evidence import EvidenceEntry, EvidenceJournal
from agent.policy import PlaybookProgress
from agent.session import AwaitingSnapshot, PendingState, SessionRecord, SessionStatus


def _tool_call_to_dict(tc: ToolCall) -> dict[str, Any]:
    return {
        "id": tc.id,
        "name": tc.name,
        "arguments": dict(tc.arguments or {}),
    }


def _tool_call_from_dict(raw: dict[str, Any]) -> ToolCall:
    args = raw.get("arguments") or {}
    if not isinstance(args, dict):
        args = {}
    return ToolCall(
        id=str(raw.get("id") or ""),
        name=str(raw.get("name") or ""),
        arguments=args,
    )


def message_to_dict(msg: Message) -> dict[str, Any]:
    role = msg.role.value if isinstance(msg.role, Role) else str(msg.role)
    data: dict[str, Any] = {"role": role, "content": msg.content}
    if msg.tool_call_id:
        data["tool_call_id"] = msg.tool_call_id
    if msg.name:
        data["name"] = msg.name
    if msg.reasoning_content:
        data["reasoning_content"] = msg.reasoning_content
    if msg.tool_calls:
        data["tool_calls"] = [_tool_call_to_dict(t) for t in msg.tool_calls]
    return data


def message_from_dict(raw: dict[str, Any]) -> Message:
    role_raw = str(raw.get("role") or "user").strip().lower()
    try:
        role = Role(role_raw)
    except ValueError:
        role = Role.USER
    tool_calls = None
    tc_raw = raw.get("tool_calls")
    if isinstance(tc_raw, list) and tc_raw:
        tool_calls = [
            _tool_call_from_dict(x) for x in tc_raw if isinstance(x, dict)
        ]
    return Message(
        role=role,
        content=raw.get("content") if raw.get("content") is not None else "",
        tool_calls=tool_calls,
        tool_call_id=(
            str(raw["tool_call_id"]) if raw.get("tool_call_id") else None
        ),
        name=str(raw["name"]) if raw.get("name") else None,
        reasoning_content=(
            str(raw["reasoning_content"])
            if raw.get("reasoning_content")
            else None
        ),
    )


def journal_to_dict(journal: EvidenceJournal) -> dict[str, Any]:
    return {
        "run_id": journal.run_id,
        "_seq": journal._seq,
        "entries": [
            {
                "id": e.id,
                "step": e.step,
                "kind": e.kind,
                "summary": e.summary,
                "tool_name": e.tool_name,
                "call_id": e.call_id,
                "is_error": e.is_error,
                "detail": e.detail,
            }
            for e in journal.entries
        ],
    }


def journal_from_dict(raw: dict[str, Any]) -> EvidenceJournal:
    entries: list[EvidenceEntry] = []
    for item in raw.get("entries") or []:
        if not isinstance(item, dict):
            continue
        entries.append(
            EvidenceEntry(
                id=str(item.get("id") or ""),
                step=int(item.get("step") or 0),
                kind=str(item.get("kind") or "observation"),  # type: ignore[arg-type]
                summary=str(item.get("summary") or ""),
                tool_name=str(item.get("tool_name") or ""),
                call_id=str(item.get("call_id") or ""),
                is_error=bool(item.get("is_error")),
                detail=str(item.get("detail") or ""),
            )
        )
    return EvidenceJournal(
        run_id=str(raw.get("run_id") or ""),
        entries=entries,
        _seq=int(raw.get("_seq") or len(entries)),
    )


def progress_to_dict(progress: PlaybookProgress | None) -> dict[str, Any] | None:
    if progress is None:
        return None
    return {
        "completed_steps": sorted(progress.completed_steps),
        "confirmed": progress.confirmed,
        "reject_counts": dict(progress.reject_counts),
        "fuse_limit": progress.fuse_limit,
    }


def progress_from_dict(raw: dict[str, Any] | None) -> PlaybookProgress | None:
    if not raw:
        return None
    steps = raw.get("completed_steps") or []
    counts = raw.get("reject_counts") or {}
    return PlaybookProgress(
        completed_steps={str(x) for x in steps},
        confirmed=bool(raw.get("confirmed")),
        reject_counts={str(k): int(v) for k, v in counts.items()},
        fuse_limit=int(raw.get("fuse_limit") or 2),
    )


def pending_to_dict(pending: PendingState | None) -> dict[str, Any] | None:
    if pending is None:
        return None
    return {
        "kind": pending.kind,
        "prompt": pending.prompt,
        "slots": list(pending.slots),
        "payload": dict(pending.payload),
        "intent": pending.intent,
        "from_run_id": pending.from_run_id,
        "evidence_ids": list(pending.evidence_ids),
    }


def pending_from_dict(raw: dict[str, Any] | None) -> PendingState | None:
    if not raw:
        return None
    kind = str(raw.get("kind") or "ask")
    if kind not in ("ask", "await_confirm"):
        kind = "ask"
    return PendingState(
        kind=kind,  # type: ignore[arg-type]
        prompt=str(raw.get("prompt") or ""),
        slots=[str(x) for x in (raw.get("slots") or [])],
        payload=dict(raw.get("payload") or {}),
        intent=str(raw.get("intent") or ""),
        from_run_id=str(raw.get("from_run_id") or ""),
        evidence_ids=[str(x) for x in (raw.get("evidence_ids") or [])],
    )


def awaiting_to_dict(snap: AwaitingSnapshot | None) -> dict[str, Any] | None:
    if snap is None:
        return None
    return {
        "run_id": snap.run_id,
        "await_token": snap.await_token,
        "kind": snap.kind,
        "prompt": snap.prompt,
        "slots": list(snap.slots),
        "payload": dict(snap.payload),
        "journal": journal_to_dict(snap.journal),
        "turn_messages": [message_to_dict(m) for m in snap.turn_messages],
        "rounds": snap.rounds,
        "tool_calls_n": snap.tool_calls_n,
        "tool_errors_n": snap.tool_errors_n,
        "started": snap.started,
        "system_before": snap.system_before,
        "system_after": snap.system_after,
        "parse_retries": snap.parse_retries,
        "max_rounds": snap.max_rounds,
        "progress": progress_to_dict(snap.progress),
        "created_at": snap.created_at,
    }


def awaiting_from_dict(raw: dict[str, Any] | None) -> AwaitingSnapshot | None:
    if not raw:
        return None
    kind = str(raw.get("kind") or "ask")
    if kind not in ("ask", "await_confirm"):
        kind = "ask"
    msgs = [
        message_from_dict(m)
        for m in (raw.get("turn_messages") or [])
        if isinstance(m, dict)
    ]
    journal_raw = raw.get("journal")
    journal = (
        journal_from_dict(journal_raw)
        if isinstance(journal_raw, dict)
        else EvidenceJournal()
    )
    return AwaitingSnapshot(
        run_id=str(raw.get("run_id") or ""),
        await_token=str(raw.get("await_token") or ""),
        kind=kind,  # type: ignore[arg-type]
        prompt=str(raw.get("prompt") or ""),
        slots=[str(x) for x in (raw.get("slots") or [])],
        payload=dict(raw.get("payload") or {}),
        journal=journal,
        turn_messages=msgs,
        rounds=int(raw.get("rounds") or 0),
        tool_calls_n=int(raw.get("tool_calls_n") or 0),
        tool_errors_n=int(raw.get("tool_errors_n") or 0),
        started=float(raw.get("started") or 0.0),
        system_before=str(raw.get("system_before") or ""),
        system_after=str(raw.get("system_after") or ""),
        parse_retries=int(raw.get("parse_retries") or 0),
        max_rounds=int(raw.get("max_rounds") or 8),
        progress=progress_from_dict(
            raw.get("progress") if isinstance(raw.get("progress"), dict) else None
        ),
        created_at=float(raw.get("created_at") or 0.0),
    )


def record_to_dict(rec: SessionRecord) -> dict[str, Any]:
    status: SessionStatus = rec.status
    return {
        "session_id": rec.session_id,
        "status": status,
        "pending": pending_to_dict(rec.pending),
        "awaiting": awaiting_to_dict(rec.awaiting),
        "active_run_id": rec.active_run_id,
    }


def record_from_dict(raw: dict[str, Any]) -> SessionRecord:
    status = str(raw.get("status") or "idle")
    if status not in ("idle", "running", "awaiting_user"):
        status = "idle"
    return SessionRecord(
        session_id=str(raw.get("session_id") or ""),
        status=status,  # type: ignore[arg-type]
        pending=pending_from_dict(
            raw.get("pending") if isinstance(raw.get("pending"), dict) else None
        ),
        awaiting=awaiting_from_dict(
            raw.get("awaiting") if isinstance(raw.get("awaiting"), dict) else None
        ),
        active_run_id=(
            str(raw["active_run_id"]) if raw.get("active_run_id") else None
        ),
    )
