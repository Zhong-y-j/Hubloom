"""事件驱动入站：Webhook → Redis 幂等 → Redis 会话串行 → Agent 一轮。

装配示例::

    url = "redis://localhost:6379/0"
    dispatcher = EventDispatcher(
        catalog=catalog,
        idempotency=create_idempotency_store(redis_url=url),
        session_gate=create_session_gate(redis_url=url),
    )
    dispatcher.bind_agent(StreamHostAgentRunner(host))
"""

from __future__ import annotations

from events.agent_runner import EventAgentRunner, StreamHostAgentRunner
from events.catalog import EventCatalog, resolve_events_skill_dir
from events.dispatcher import EventDispatcher
from events.idempotency import (
    EventDispatchResult,
    IdempotencyStore,
    RedisIdempotencyStore,
    create_idempotency_store,
)
from events.models import HubloomEvent, normalize_event
from events.session_gate import (
    RedisSessionGate,
    SessionGate,
    create_session_gate,
)

__all__ = [
    "EventAgentRunner",
    "EventCatalog",
    "EventDispatcher",
    "EventDispatchResult",
    "HubloomEvent",
    "IdempotencyStore",
    "RedisIdempotencyStore",
    "RedisSessionGate",
    "SessionGate",
    "StreamHostAgentRunner",
    "create_idempotency_store",
    "create_session_gate",
    "normalize_event",
    "resolve_events_skill_dir",
]
