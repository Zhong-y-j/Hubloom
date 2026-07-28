"""按 session_id 串行（仅 Redis）：同一会话同时只跑一条事件。

键：``hubloom:event:lock:session:{session_id}``（SET NX + TTL）。
不同 ``event_id`` 会排队等锁，锁释放后再跑，不丢弃。
"""

from __future__ import annotations

import asyncio
import uuid
from collections.abc import Awaitable, Callable
from typing import Protocol, TypeVar

from redis.asyncio import Redis

T = TypeVar("T")


class SessionGate(Protocol):
    async def run(self, session_id: str, factory: Callable[[], Awaitable[T]]) -> T: ...


class RedisSessionGate:
    """Redis 会话锁。"""

    def __init__(
        self,
        redis: Redis,
        *,
        key_prefix: str = "hubloom:event:lock:session:",
        lock_ttl_seconds: int = 600,
        wait_poll_seconds: float = 0.05,
        wait_timeout_seconds: float = 600.0,
    ) -> None:
        self._redis = redis
        self._prefix = key_prefix
        self._ttl = max(30, int(lock_ttl_seconds))
        self._poll = max(0.01, float(wait_poll_seconds))
        self._wait_timeout = max(1.0, float(wait_timeout_seconds))

    def _key(self, session_id: str) -> str:
        return f"{self._prefix}{session_id}"

    async def run(self, session_id: str, factory: Callable[[], Awaitable[T]]) -> T:
        sid = (session_id or "").strip()
        if not sid:
            raise ValueError("session_id 不能为空")
        token = uuid.uuid4().hex
        key = self._key(sid)
        loop = asyncio.get_running_loop()
        deadline = loop.time() + self._wait_timeout

        while True:
            ok = await self._redis.set(key, token, nx=True, ex=self._ttl)
            if ok:
                break
            if loop.time() >= deadline:
                raise TimeoutError(f"等待会话锁超时: session_id={sid!r}")
            await asyncio.sleep(self._poll)

        try:
            return await factory()
        finally:
            current = await self._redis.get(key)
            if current == token:
                await self._redis.delete(key)


def create_session_gate(
    *,
    redis_url: str,
    redis: Redis | None = None,
) -> RedisSessionGate:
    """创建 Redis 会话门闩；``redis_url`` 必填（或传入已有 ``redis`` 客户端）。"""
    client = redis
    if client is None:
        url = (redis_url or "").strip()
        if not url:
            raise ValueError("redis_url 不能为空（事件会话串行仅支持 Redis）")
        client = Redis.from_url(url, decode_responses=True)
    return RedisSessionGate(client)
