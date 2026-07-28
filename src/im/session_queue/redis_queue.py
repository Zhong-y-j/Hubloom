"""按 session_id 的 Redis 队列 + 锁（IM 入站串行）。

键：
- ``hubloom:im:q:{session_id}``           待处理 List
- ``hubloom:im:processing:{session_id}``  在途（RPOPLPUSH），防崩溃丢任务
- ``hubloom:im:lock:{session_id}``        消费者锁
- ``hubloom:im:dedupe:{dedupe_key}``      幂等
- ``hubloom:im:active:{session_id}``      当前运行中的 job 元数据（供后期打断）
- ``hubloom:im:cancel:{session_id}``      取消标记（本期仅暴露 API，消费路径不自动打断）

``take_jobs`` 当前最多返回 1 条；签名为 list，后期可一次取出多条再合并。
"""

from __future__ import annotations

import json
import uuid
from typing import Any

from redis.asyncio import Redis

from im.session_queue.job import EnqueueResult, SessionJob


class RedisSessionQueue:
    """IM 会话队列（Redis）。"""

    def __init__(
        self,
        redis: Redis,
        *,
        key_prefix: str = "hubloom:im:",
        lock_ttl_seconds: int = 600,
        dedupe_ttl_seconds: int = 24 * 3600,
    ) -> None:
        self._redis = redis
        self._prefix = key_prefix
        self._lock_ttl = max(30, int(lock_ttl_seconds))
        self._dedupe_ttl = max(60, int(dedupe_ttl_seconds))

    @property
    def redis(self) -> Redis:
        return self._redis

    def _q(self, session_id: str) -> str:
        return f"{self._prefix}q:{session_id}"

    def _processing(self, session_id: str) -> str:
        return f"{self._prefix}processing:{session_id}"

    def _lock(self, session_id: str) -> str:
        return f"{self._prefix}lock:{session_id}"

    def _dedupe(self, dedupe_key: str) -> str:
        return f"{self._prefix}dedupe:{dedupe_key}"

    def _active(self, session_id: str) -> str:
        return f"{self._prefix}active:{session_id}"

    def _cancel(self, session_id: str) -> str:
        return f"{self._prefix}cancel:{session_id}"

    async def enqueue(self, job: SessionJob) -> EnqueueResult:
        sid = (job.session_id or "").strip()
        if not sid:
            return EnqueueResult(accepted=False, reason="session_id 为空")
        if not (job.text or "").strip() and job.source == "wecom":
            # 允许非文本由上层直接推送；队列只收有正文的处理任务
            pass

        dedupe = (job.dedupe_key or "").strip()
        if dedupe:
            ok = await self._redis.set(
                self._dedupe(dedupe),
                job.job_id,
                nx=True,
                ex=self._dedupe_ttl,
            )
            if not ok:
                return EnqueueResult(
                    accepted=False,
                    duplicate=True,
                    job_id=job.job_id,
                    session_id=sid,
                    reason="duplicate dedupe_key",
                )

        await self._redis.lpush(self._q(sid), job.to_json())
        return EnqueueResult(
            accepted=True,
            duplicate=False,
            job_id=job.job_id,
            session_id=sid,
        )

    async def try_acquire_lock(self, session_id: str) -> str | None:
        """抢消费者锁；成功返回 lock token，失败返回 None。"""
        sid = (session_id or "").strip()
        if not sid:
            return None
        token = uuid.uuid4().hex
        ok = await self._redis.set(
            self._lock(sid), token, nx=True, ex=self._lock_ttl
        )
        return token if ok else None

    async def refresh_lock(self, session_id: str, token: str) -> bool:
        sid = (session_id or "").strip()
        key = self._lock(sid)
        current = await self._redis.get(key)
        if current != token:
            return False
        await self._redis.expire(key, self._lock_ttl)
        return True

    async def release_lock(self, session_id: str, token: str) -> None:
        sid = (session_id or "").strip()
        key = self._lock(sid)
        current = await self._redis.get(key)
        if current == token:
            await self._redis.delete(key)

    async def queue_length(self, session_id: str) -> int:
        return int(await self._redis.llen(self._q(session_id)) or 0)

    async def take_jobs(self, session_id: str, *, max_jobs: int = 1) -> list[SessionJob]:
        """取出待处理 Job（经 processing 列表）。

        当前固定按最多 1 条取（``max_jobs`` 上限裁剪）；后期合并时可传入更大 ``max_jobs``
        或在本方法内一次引流多条，调用方已按 ``list[SessionJob]`` 处理。
        """
        sid = (session_id or "").strip()
        if not sid:
            return []
        # 本期固定取 1 条。保留 max_jobs 参数供后期合并引流；签名已是 list。
        _ = max_jobs
        limit = 1

        jobs: list[SessionJob] = []
        q = self._q(sid)
        proc = self._processing(sid)
        for _ in range(limit):
            # LPUSH 入队 + RPOPLPUSH 出队 → FIFO
            raw = await self._redis.rpoplpush(q, proc)
            if raw is None:
                break
            if isinstance(raw, bytes):
                raw = raw.decode("utf-8")
            try:
                jobs.append(SessionJob.from_json(raw))
            except Exception:
                await self._redis.lrem(proc, 1, raw)
                continue
        return jobs

    async def ack_jobs(self, session_id: str, jobs: list[SessionJob]) -> None:
        """从 processing 移除已完成 Job。"""
        sid = (session_id or "").strip()
        if not sid or not jobs:
            return
        proc = self._processing(sid)
        for job in jobs:
            payload = job.to_json()
            await self._redis.lrem(proc, 1, payload)

    async def reclaim_processing(self, session_id: str) -> int:
        """把 processing 中残留任务塞回队列头（崩溃恢复，kick 时调用）。"""
        sid = (session_id or "").strip()
        if not sid:
            return 0
        proc = self._processing(sid)
        q = self._q(sid)
        n = 0
        while True:
            # processing 由 RPOPLPUSH 以 LPUSH 写入，右侧更旧；RPOP 后 RPUSH 回 q 保持 FIFO
            raw = await self._redis.rpop(proc)
            if raw is None:
                break
            await self._redis.rpush(q, raw)
            n += 1
        return n

    async def set_active(self, session_id: str, job: SessionJob) -> None:
        sid = (session_id or "").strip()
        payload = json.dumps(
            {
                "job_id": job.job_id,
                "source": job.source,
                "created_at": job.created_at,
            },
            ensure_ascii=False,
        )
        await self._redis.set(self._active(sid), payload, ex=self._lock_ttl)

    async def clear_active(self, session_id: str) -> None:
        await self._redis.delete(self._active(session_id))

    async def get_active(self, session_id: str) -> dict[str, Any] | None:
        raw = await self._redis.get(self._active(session_id))
        if not raw:
            return None
        if isinstance(raw, bytes):
            raw = raw.decode("utf-8")
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            return None
        return data if isinstance(data, dict) else None

    async def request_cancel(self, session_id: str, *, reason: str = "") -> None:
        """标记取消（供后期打断 Agent）。本期 Worker 主路径不自动调用。"""
        sid = (session_id or "").strip()
        if not sid:
            return
        payload = json.dumps(
            {"reason": reason, "token": uuid.uuid4().hex},
            ensure_ascii=False,
        )
        await self._redis.set(self._cancel(sid), payload, ex=self._lock_ttl)

    async def clear_cancel(self, session_id: str) -> None:
        await self._redis.delete(self._cancel(session_id))

    async def is_cancel_requested(self, session_id: str) -> bool:
        return bool(await self._redis.get(self._cancel(session_id)))


def create_session_queue(
    *,
    redis_url: str,
    redis: Redis | None = None,
    lock_ttl_seconds: int = 600,
    dedupe_ttl_seconds: int = 24 * 3600,
) -> RedisSessionQueue:
    """创建 IM Redis 会话队列。"""
    client = redis
    if client is None:
        url = (redis_url or "").strip()
        if not url:
            raise ValueError("redis_url 不能为空")
        client = Redis.from_url(url, decode_responses=True)
    return RedisSessionQueue(
        client,
        lock_ttl_seconds=lock_ttl_seconds,
        dedupe_ttl_seconds=dedupe_ttl_seconds,
    )
