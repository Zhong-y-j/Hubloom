"""IM 会话 Redis 队列：按用户 session 串行入站任务。

对外最小用法::

    from im.session_queue import (
        SessionJob,
        SessionWorker,
        create_session_queue,
    )

    queue = create_session_queue(redis_url="redis://localhost:6379/0")
    worker = SessionWorker(queue, handler=my_handle_jobs)

    async def my_handle_jobs(jobs: list[SessionJob]) -> None:
        # 现在 len(jobs)==1；后期合并时可能 >1
        job = jobs[0]
        ...

    await worker.enqueue_and_kick(
        SessionJob(session_id="wecom:Uid", source="wecom", text="你好")
    )

企微适配器可注入同一套 queue/worker，见 ``WeComChatAdapter(session_queue=..., session_worker=...)``。
"""

from __future__ import annotations

from im.session_queue.job import EnqueueResult, SessionJob
from im.session_queue.redis_queue import RedisSessionQueue, create_session_queue
from im.session_queue.worker import JobHandler, SessionWorker

__all__ = [
    "EnqueueResult",
    "JobHandler",
    "RedisSessionQueue",
    "SessionJob",
    "SessionWorker",
    "create_session_queue",
]
