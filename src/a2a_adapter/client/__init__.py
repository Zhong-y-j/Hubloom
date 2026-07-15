"""A2A 出站适配层。"""

from a2a_adapter.client.registry import RemoteAgent, get_agent, load_agents

__all__ = [
    "RemoteAgent",
    "load_agents",
    "get_agent",
    "delegate",
    "send_and_wait_answer",
]


def __getattr__(name: str):
    # 延迟导入，避免 `python -m a2a_adapter.client.transport` 时重复加载警告
    if name in ("delegate", "send_and_wait_answer"):
        from a2a_adapter.client import transport as _transport

        return getattr(_transport, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")

