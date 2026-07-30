"""Events 最小演示：目录 → 规范化 → Redis 幂等 + 会话串行（假 Agent）。

需本机 Redis（例如 ``docker run -d --name redis -p 6379:6379 redis:7``）。

用法（仓库根目录）::

    HUBLOOM_EVENTS_REDIS_URL=redis://localhost:6379/0 \\
      PYTHONPATH=src .venv/bin/python tests/test_events.py
"""

from __future__ import annotations

import asyncio
import os
from pathlib import Path

from agent.run import RunResult
from core.models import Message
from events import (
    EventCatalog,
    EventDispatcher,
    create_idempotency_store,
    create_session_gate,
    normalize_event,
)
from events.catalog import render_event_trigger
from events.idempotency import EventDispatchResult
from redis.asyncio import Redis


class _FakeAgent:
    """假装 Agent：记录调用顺序，返回固定摘要。"""

    def __init__(self) -> None:
        self.calls: list[str] = []

    async def run_event_turn(
        self,
        trigger: Message,
        *,
        session_id: str,
        present_mode: str = "markdown",
        bearer_token: str | None = None,
        trigger_source: str = "event",
        wait_profile: str | None = None,
    ) -> RunResult:
        _ = present_mode, bearer_token, trigger_source, session_id, wait_profile
        mark = "unknown"
        for line in (trigger.content or "").splitlines():
            if line.startswith("event_id:"):
                mark = line.split(":", 1)[-1].strip()
                break
        self.calls.append(mark)
        await asyncio.sleep(0.05)
        return RunResult(ok=True, content=f"fake-ok:{mark}", think_rounds=1)


def _redis_url() -> str:
    return (
        os.environ.get("HUBLOOM_EVENTS_REDIS_URL") or "redis://localhost:6379/0"
    ).strip()


async def demo_events() -> None:
    import uuid

    run_tag = uuid.uuid4().hex[:8]
    redis_url = _redis_url()
    print("【存储】 Redis", redis_url)
    print("【本轮后缀】", run_tag)

    # 连通性检查
    client = Redis.from_url(redis_url, decode_responses=True)
    try:
        pong = await client.ping()
        print("【Redis ping】", pong)
    except Exception as exc:
        raise SystemExit(
            f"无法连接 Redis（{redis_url}）。请先启动容器，例如：\n"
            "  docker run -d --name redis -p 6379:6379 redis:7\n"
            f"详情: {exc}"
        ) from exc
    finally:
        await client.aclose()

    events_dir = Path("skills/events")
    catalog = EventCatalog.load(events_dir=events_dir)
    print("【已发现事件类型】", catalog.types())

    eid1 = f"evt-demo-001-{run_tag}"
    eid2 = f"evt-demo-002-{run_tag}"
    raw = {
        "event_id": eid1,
        "type": "locker.created",
        "session_id": "demo-user-1",
        "payload": {"deviceId": "LK-A-001"},
        "occurred_at": "2026-07-28T15:00:00+08:00",
    }
    event = normalize_event(raw)
    entry = catalog.get(event.type)
    trigger = render_event_trigger(event, entry)
    print("【触发文预览】", trigger[:200].replace("\n", " "), "…")

    redis = Redis.from_url(redis_url, decode_responses=True)
    fake = _FakeAgent()
    dispatcher = EventDispatcher(
        catalog=catalog,
        idempotency=create_idempotency_store(redis_url=redis_url, redis=redis),
        session_gate=create_session_gate(redis_url=redis_url, redis=redis),
    )
    dispatcher.bind_agent(fake)

    r1 = await dispatcher.dispatch(event)
    print("【首次】", r1.to_dict())

    r2 = await dispatcher.dispatch(event)
    print("【重放同 event_id】", r2.to_dict())
    print("【Agent 调用次数】", len(fake.calls), "calls=", fake.calls)

    event_b = normalize_event(
        {
            "event_id": eid2,
            "type": "locker.created",
            "session_id": "demo-user-1",
            "payload": {"deviceId": "LK-A-002"},
        }
    )
    r3 = await dispatcher.dispatch(event_b)
    print("【新 event_id】", r3.to_dict())
    print("【Agent 调用次数】", len(fake.calls), "calls=", fake.calls)

    fake2 = _FakeAgent()
    redis2 = Redis.from_url(redis_url, decode_responses=True)
    d2 = EventDispatcher(
        catalog=catalog,
        idempotency=create_idempotency_store(redis_url=redis_url, redis=redis2),
        session_gate=create_session_gate(redis_url=redis_url, redis=redis2),
    )
    d2.bind_agent(fake2)

    async def _one(eid: str, device: str) -> EventDispatchResult:
        return await d2.dispatch(
            normalize_event(
                {
                    "event_id": eid,
                    "type": "locker.created",
                    "session_id": f"demo-user-serial-{run_tag}",
                    "payload": {"deviceId": device},
                }
            )
        )

    results = await asyncio.gather(
        _one(f"evt-s-1-{run_tag}", "D1"),
        _one(f"evt-s-2-{run_tag}", "D2"),
    )
    print("【并发同 session】调用顺序", fake2.calls)
    print("【并发结果】", [r.event_id for r in results])

    await redis.aclose()
    await redis2.aclose()


if __name__ == "__main__":
    asyncio.run(demo_events())
