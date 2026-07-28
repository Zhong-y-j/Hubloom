"""按 session 消费 Redis 队列：持锁 FIFO，一次处理 take_jobs 返回的列表。

当前 ``take_jobs`` 只给出 1 条，故行为是一条一条跑。
Handler 签名为 ``list[SessionJob]``，后期合并多条时无需改 Worker 外壳。
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from typing import Any

from loguru import logger

from im.session_queue.job import SessionJob
from im.session_queue.redis_queue import RedisSessionQueue

# jobs 列表：现在长度恒为 1；合并期可能 >1
JobHandler = Callable[[list[SessionJob]], Awaitable[None]]


class SessionWorker:
    """为每个 session 维护至多一个消费协程。"""

    def __init__(
        self,
        queue: RedisSessionQueue,
        handler: JobHandler,
        *,
        idle_poll_seconds: float = 0.05,
        lock_refresh_every_seconds: float = 30.0,
    ) -> None:
        self.queue = queue
        self.handler = handler
        self._idle_poll = max(0.01, float(idle_poll_seconds))
        self._refresh_every = max(5.0, float(lock_refresh_every_seconds))
        self._tasks: dict[str, asyncio.Task[Any]] = {}
        self._guard = asyncio.Lock()

    async def ensure_consumer(self, session_id: str) -> None:
        """若该 session 尚无消费者，则尝试抢锁并启动。"""
        sid = (session_id or "").strip()
        if not sid:
            return
        async with self._guard:
            existing = self._tasks.get(sid)
            if existing is not None and not existing.done():
                return
            token = await self.queue.try_acquire_lock(sid)
            if token is None:
                return
            await self.queue.reclaim_processing(sid)
            task = asyncio.create_task(
                self._run_session(sid, token),
                name=f"im-session-worker:{sid}",
            )
            self._tasks[sid] = task

            def _cleanup(t: asyncio.Task[Any], *, session=sid) -> None:
                self._tasks.pop(session, None)
                _ = t.exception() if not t.cancelled() else None

            task.add_done_callback(_cleanup)

    async def enqueue_and_kick(self, job: SessionJob):
        """入队并确保消费者在跑。对外常用入口。"""
        result = await self.queue.enqueue(job)
        if result.accepted and result.session_id:
            await self.ensure_consumer(result.session_id)
        return result

    async def _run_session(self, session_id: str, token: str) -> None:
        loop = asyncio.get_running_loop()
        last_refresh = loop.time()
        try:
            while True:
                now = loop.time()
                if now - last_refresh >= self._refresh_every:
                    ok = await self.queue.refresh_lock(session_id, token)
                    if not ok:
                        logger.warning(
                            "im session lock lost | session_id={}", session_id
                        )
                        return
                    last_refresh = now

                jobs = await self.queue.take_jobs(session_id)
                if not jobs:
                    # 双检：短暂等待后再看队列，避免 enqueue 竞态漏消费
                    await asyncio.sleep(self._idle_poll)
                    if await self.queue.queue_length(session_id) > 0:
                        continue
                    return

                try:
                    await self.queue.clear_cancel(session_id)
                    await self.queue.set_active(session_id, jobs[0])
                    await self.handler(jobs)
                except Exception:
                    logger.exception(
                        "im session handler failed | session_id={} | job_ids={}",
                        session_id,
                        [j.job_id for j in jobs],
                    )
                finally:
                    await self.queue.ack_jobs(session_id, jobs)
                    await self.queue.clear_active(session_id)
        finally:
            await self.queue.release_lock(session_id, token)
            # 释放后若又有积压，再 kick（可能由其他协程抢到锁）
            if await self.queue.queue_length(session_id) > 0:
                await self.ensure_consumer(session_id)
