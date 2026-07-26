"""入站事件契约与规范化。"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class HubloomEvent:
    """规范化后的业务事件（调度层输入）。"""

    event_id: str
    type: str
    session_id: str
    payload: dict[str, Any] = field(default_factory=dict)
    occurred_at: str | None = None
    bearer_token: str | None = None
    instruction: str | None = None


def normalize_event(raw: dict[str, Any]) -> HubloomEvent:
    """从请求 JSON 规范化；缺关键字段时抛 ``ValueError``。"""
    if not isinstance(raw, dict):
        raise ValueError("事件 body 须为 JSON object")

    event_id = str(raw.get("event_id") or "").strip()
    if not event_id:
        raise ValueError("event_id 不能为空")

    event_type = str(raw.get("type") or "").strip()
    if not event_type:
        raise ValueError("type 不能为空")

    session_id = str(raw.get("session_id") or "").strip()
    if not session_id:
        raise ValueError("session_id 不能为空")

    payload = raw.get("payload")
    if payload is None:
        payload = {}
    if not isinstance(payload, dict):
        raise ValueError("payload 须为 object")

    occurred_at = raw.get("occurred_at")
    occurred = str(occurred_at).strip() if occurred_at is not None else None
    if occurred == "":
        occurred = None

    token_raw = raw.get("bearer_token")
    bearer = str(token_raw).strip() if token_raw is not None else None
    if bearer == "":
        bearer = None

    instr_raw = raw.get("instruction")
    instruction = str(instr_raw).strip() if instr_raw is not None else None
    if instruction == "":
        instruction = None

    return HubloomEvent(
        event_id=event_id,
        type=event_type,
        session_id=session_id,
        payload=dict(payload),
        occurred_at=occurred,
        bearer_token=bearer,
        instruction=instruction,
    )
