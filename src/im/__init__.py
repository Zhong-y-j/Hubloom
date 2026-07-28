"""IM 多端触达（企微等）与按 session 的 Redis 入站队列。

会话队列（外部可直接使用）::

    from im import SessionJob, SessionWorker, create_session_queue

    queue = create_session_queue(redis_url="redis://localhost:6379/0")
    worker = SessionWorker(queue, handler=...)
    await worker.enqueue_and_kick(SessionJob(...))

企微::

    from im.wecom import WeComChatAdapter
"""

from __future__ import annotations

from im.session_queue import (
    EnqueueResult,
    JobHandler,
    RedisSessionQueue,
    SessionJob,
    SessionWorker,
    create_session_queue,
)

__all__ = [
    "EnqueueResult",
    "JobHandler",
    "RedisSessionQueue",
    "SessionJob",
    "SessionWorker",
    "create_session_queue",
]
