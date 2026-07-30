"""事件层调用 Agent 的抽象（不依赖 HubloomRuntime 模块）。

调用方注入任意能跑完一轮并返回 ``RunResult`` 的实现；
Serve 用 ``StreamHostAgentRunner`` 包装带 ``run_stream`` 的对象。
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
        wait_profile: str | None = None,
    ) -> RunResult:
        """执行一轮编排，返回最终 ``RunResult``。"""
        ...


class StreamHostAgentRunner:
    """适配提供 ``async run_stream(...)`` 的宿主。

    事件默认 ``wait_profile=no_wait``（无人值守，禁止 ask 挂死）。
    """

    def __init__(
        self,
        host: Any,
        *,
        wait_profile: str = "no_wait",
    ) -> None:
        if not hasattr(host, "run_stream"):
            raise TypeError("host 须提供 async run_stream(...)")
        self._host = host
        self._wait_profile = (wait_profile or "no_wait").strip() or "no_wait"

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
        del present_mode  # Typed ReAct 无 present_mode
        profile = (wait_profile or self._wait_profile).strip() or self._wait_profile
        final: RunResult | None = None
        async for item in self._host.run_stream(
            trigger,
            session_id=session_id,
            bearer_token=bearer_token,
            wait_profile=profile,
            trigger_source=trigger_source,
        ):
            if isinstance(item, RunResult):
                final = item
        if final is None:
            return RunResult(ok=False, error="未收到编排结果")
        return final
