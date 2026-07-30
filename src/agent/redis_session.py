"""Redis SessionStore + 按 session 分布式锁（唯一实现，无进程内存路径）。"""

from __future__ import annotations

import asyncio
import json
import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

from redis import Redis
from redis.asyncio import Redis as AsyncRedis

from agent.session import SessionRecord
from agent.session_serialize import record_from_dict, record_to_dict


class RedisSessionStore:
    """挂起 / pending 外置到 Redis。"""

    def __init__(
        self,
        redis: Redis,
        *,
        key_prefix: str = "hubloom:agent:session:",
        ttl_seconds: int = 7 * 24 * 3600,
    ) -> None:
        self._redis = redis
        self._prefix = key_prefix
        self._ttl = max(60, int(ttl_seconds))

    def _key(self, session_id: str) -> str:
        return f"{self._prefix}{session_id}"

    def get(self, session_id: str) -> SessionRecord | None:
        sid = (session_id or "").strip()
        if not sid:
            return None
        raw = self._redis.get(self._key(sid))
        if not raw:
            return None
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            return None
        if not isinstance(data, dict):
            return None
        rec = record_from_dict(data)
        if not rec.session_id:
            rec.session_id = sid
        return rec

    def put(self, record: SessionRecord) -> None:
        sid = (record.session_id or "").strip()
        if not sid:
            raise ValueError("session_id 不能为空")
        payload = json.dumps(record_to_dict(record), ensure_ascii=False)
        self._redis.set(self._key(sid), payload, ex=self._ttl)

    def delete(self, session_id: str) -> None:
        sid = (session_id or "").strip()
        if not sid:
            return
        self._redis.delete(self._key(sid))


class RedisSessionLock:
    """按 session_id 串行（SET NX + TTL）；不同会话可并行。"""

    def __init__(
        self,
        redis: AsyncRedis,
        *,
        key_prefix: str = "hubloom:agent:lock:session:",
        lock_ttl_seconds: int = 1800,
        wait_poll_seconds: float = 0.05,
        wait_timeout_seconds: float = 1800.0,
    ) -> None:
        self._redis = redis
        self._prefix = key_prefix
        self._ttl = max(30, int(lock_ttl_seconds))
        self._poll = max(0.01, float(wait_poll_seconds))
        self._wait_timeout = max(1.0, float(wait_timeout_seconds))

    def _key(self, session_id: str) -> str:
        return f"{self._prefix}{session_id}"

    async def acquire(self, session_id: str) -> str:
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
                return token
            if loop.time() >= deadline:
                raise TimeoutError(f"等待会话锁超时: session_id={sid!r}")
            await asyncio.sleep(self._poll)

    async def release(self, session_id: str, token: str) -> None:
        sid = (session_id or "").strip()
        if not sid:
            return
        key = self._key(sid)
        current = await self._redis.get(key)
        if current == token:
            await self._redis.delete(key)

    @asynccontextmanager
    async def hold(self, session_id: str) -> AsyncIterator[None]:
        token = await self.acquire(session_id)
        try:
            yield
        finally:
            await self.release(session_id, token)


def open_redis_clients(url: str) -> tuple[Redis, AsyncRedis]:
    """同步 + 异步客户端（Store 用同步，Lock 用异步）。"""
    u = (url or "").strip()
    if not u:
        raise ValueError("redis.url 不能为空")
    sync_client = Redis.from_url(u, decode_responses=True)
    async_client = AsyncRedis.from_url(u, decode_responses=True)
    return sync_client, async_client


def create_redis_session_backends(
    url: str,
    *,
    session_ttl_seconds: int | None = None,
    lock_ttl_seconds: int | None = None,
) -> tuple[RedisSessionStore, RedisSessionLock, Redis, AsyncRedis]:
    sync_client, async_client = open_redis_clients(url)
    store_kw: dict[str, Any] = {}
    lock_kw: dict[str, Any] = {}
    if session_ttl_seconds is not None:
        store_kw["ttl_seconds"] = session_ttl_seconds
    if lock_ttl_seconds is not None:
        lock_kw["lock_ttl_seconds"] = lock_ttl_seconds
        lock_kw["wait_timeout_seconds"] = float(lock_ttl_seconds)
    store = RedisSessionStore(sync_client, **store_kw)
    lock = RedisSessionLock(async_client, **lock_kw)
    return store, lock, sync_client, async_client
