"""事件层调用 Agent 的抽象（不依赖 HubloomRuntime 模块）。

调用方注入任意能跑完一轮并返回 ``RunResult`` 的实现；
示例站可用 ``StreamHostAgentRunner`` 包装带 ``run_stream`` 的对象。
"""

from __future__ import annotations

from typing import Any, Protocol

from agent.run import RunResult
from core.models import Message


class EventAgentRunner(Protocol):
    """事件 Dispatcher 唯一需要的「跑一轮 Agent」能力。"""

    async def run_event_turn(
        self,
        trigger: Message,
        *,
        session_id: str,
        present_mode: str = "markdown",
        bearer_token: str | None = None,
        trigger_source: str = "event",
    ) -> RunResult:
        """执行一轮编排，返回最终 ``RunResult``。"""
        ...


class StreamHostAgentRunner:
    """适配提供 ``async run_stream(...)`` 的宿主（如示例站里的 Runtime 实例）。

    有意不 import ``runtime``，避免 events ↔ runtime 环依赖；由装配方传入宿主。
    """

    def __init__(self, host: Any) -> None:
        if not hasattr(host, "run_stream"):
            raise TypeError("host 须提供 async run_stream(...)")
        self._host = host

    async def run_event_turn(
        self,
        trigger: Message,
        *,
        session_id: str,
        present_mode: str = "markdown",
        bearer_token: str | None = None,
        trigger_source: str = "event",
    ) -> RunResult:
        final: RunResult | None = None
        async for item in self._host.run_stream(
            trigger,
            session_id=session_id,
            present_mode=present_mode,
            bearer_token=bearer_token,
            trigger_source=trigger_source,
        ):
            if isinstance(item, RunResult):
                final = item
        if final is None:
            return RunResult(ok=False, error="未收到编排结果")
        return final
