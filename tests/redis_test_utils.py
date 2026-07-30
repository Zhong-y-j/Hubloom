"""测试用 Redis Session 后端（fakeredis，无外部 Redis）。"""

from __future__ import annotations

from agent.redis_session import RedisSessionLock, RedisSessionStore


def make_fake_session_backends() -> tuple[RedisSessionStore, RedisSessionLock]:
    from fakeredis import FakeStrictRedis
    from fakeredis.aioredis import FakeRedis

    sync = FakeStrictRedis(decode_responses=True)
    async_r = FakeRedis(decode_responses=True)
    return RedisSessionStore(sync), RedisSessionLock(async_r)
