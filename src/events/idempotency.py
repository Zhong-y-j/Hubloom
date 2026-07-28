"""事件幂等（仅 Redis）：同一 event_id 只真正跑一次 Agent。

键：``hubloom:event:idem:{event_id}`` → JSON 结果。
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Protocol

from redis.asyncio import Redis


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

    @classmethod
    def from_dict(
        cls, data: dict[str, Any], *, duplicate: bool | None = None
    ) -> EventDispatchResult:
        return cls(
            event_id=str(data.get("event_id") or ""),
            session_id=str(data.get("session_id") or ""),
            type=str(data.get("type") or ""),
            ok=bool(data.get("ok")),
            duplicate=bool(data.get("duplicate")) if duplicate is None else duplicate,
            summary=str(data.get("summary") or ""),
            error=(str(data["error"]) if data.get("error") is not None else None),
            turn_count=int(data.get("turn_count") or 0),
        )


class IdempotencyStore(Protocol):
    async def get(self, event_id: str) -> EventDispatchResult | None: ...

    async def put(self, result: EventDispatchResult) -> None: ...


class RedisIdempotencyStore:
    """Redis 幂等存储。"""

    def __init__(
        self,
        redis: Redis,
        *,
        key_prefix: str = "hubloom:event:idem:",
        ttl_seconds: int = 7 * 24 * 3600,
    ) -> None:
        self._redis = redis
        self._prefix = key_prefix
        self._ttl = max(60, int(ttl_seconds))

    def _key(self, event_id: str) -> str:
        return f"{self._prefix}{event_id}"

    async def get(self, event_id: str) -> EventDispatchResult | None:
        raw = await self._redis.get(self._key(event_id))
        if not raw:
            return None
        if isinstance(raw, bytes):
            raw = raw.decode("utf-8")
        data = json.loads(raw)
        if not isinstance(data, dict):
            return None
        return EventDispatchResult.from_dict(data, duplicate=False)

    async def put(self, result: EventDispatchResult) -> None:
        payload = json.dumps(result.to_dict(), ensure_ascii=False)
        await self._redis.set(self._key(result.event_id), payload, ex=self._ttl)


def create_idempotency_store(
    *,
    redis_url: str,
    ttl_seconds: int = 7 * 24 * 3600,
    redis: Redis | None = None,
) -> RedisIdempotencyStore:
    """创建 Redis 幂等存储；``redis_url`` 必填（或传入已有 ``redis`` 客户端）。"""
    client = redis
    if client is None:
        url = (redis_url or "").strip()
        if not url:
            raise ValueError("redis_url 不能为空（事件幂等仅支持 Redis）")
        client = Redis.from_url(url, decode_responses=True)
    return RedisIdempotencyStore(client, ttl_seconds=ttl_seconds)
