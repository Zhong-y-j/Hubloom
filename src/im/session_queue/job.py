"""IM 会话队列：按 session 串行的 Job 模型。

当前消费一次只取 1 条；``merged_from`` / ``take_jobs`` 返回 list，便于后期合并多条。
"""

from __future__ import annotations

import json
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class SessionJob:
    """会话队列中的一条待处理任务。

    后期若合并多条：可把多条 ``text`` 拼进一轮，并把各 ``job_id`` 写入 ``merged_from``。
    """

    session_id: str
    source: str  # wecom | web | event | …
    text: str
    job_id: str = field(default_factory=lambda: uuid.uuid4().hex)
    created_at: str = field(default_factory=_utc_now_iso)
    dedupe_key: str | None = None
    bearer_token: str | None = None
    meta: dict[str, Any] = field(default_factory=dict)
    # 后期合并用：被合成进本 Job 的原始 job_id 列表；单条处理时为空
    merged_from: list[str] = field(default_factory=list)

    def to_json(self) -> str:
        return json.dumps(asdict(self), ensure_ascii=False)

    @classmethod
    def from_json(cls, raw: str | bytes) -> SessionJob:
        if isinstance(raw, bytes):
            raw = raw.decode("utf-8")
        data = json.loads(raw)
        if not isinstance(data, dict):
            raise ValueError("SessionJob JSON 须为 object")
        meta = data.get("meta") if isinstance(data.get("meta"), dict) else {}
        merged = data.get("merged_from")
        if not isinstance(merged, list):
            merged = []
        return cls(
            session_id=str(data.get("session_id") or "").strip(),
            source=str(data.get("source") or "").strip() or "unknown",
            text=str(data.get("text") or ""),
            job_id=str(data.get("job_id") or uuid.uuid4().hex),
            created_at=str(data.get("created_at") or _utc_now_iso()),
            dedupe_key=(
                str(data["dedupe_key"]).strip()
                if data.get("dedupe_key") is not None
                else None
            )
            or None,
            bearer_token=(
                str(data["bearer_token"]).strip()
                if data.get("bearer_token") is not None
                else None
            )
            or None,
            meta=dict(meta),
            merged_from=[str(x) for x in merged if str(x).strip()],
        )


@dataclass(frozen=True)
class EnqueueResult:
    accepted: bool
    duplicate: bool = False
    job_id: str | None = None
    session_id: str | None = None
    reason: str | None = None
