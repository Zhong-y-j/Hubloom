"""灵枢 Hub：ReAct + MCP 单链路编排。"""

from __future__ import annotations

import time
import uuid
from collections.abc import AsyncIterator
from typing import Any

from agents.core.agent_log import clear_turn_id, hub_log, set_turn_id
from agents.core.events import (
    AgentEvent,
    ErrorEvent,
    HubPhaseEvent,
    HubTurnCompleteEvent,
)
from agents.hub.models import ROUTE_CLARIFY_ONLY, ROUTE_DIRECT_REPLY, HubTurnOutcome
from agents.react.agent import ReActAgent


class CortexHub:
    """编排 ReAct（澄清 + MCP 工具循环）的中枢。

    单轮 ``run_turn_stream(user_message)``：
    1. ReAct 结合 MCP 工具澄清或执行
    2. ``HubTurnCompleteEvent`` 汇总 ``final_user_message``
    """

    def __init__(
        self,
        react: ReActAgent,
        *,
        mcp_bindings: Any | None = None,
    ) -> None:
        self.react = react
        self.last_outcome: HubTurnOutcome | None = None
        self._mcp_bindings = mcp_bindings

    async def close(self) -> None:
        """释放 MCP 连接等资源。"""
        if self._mcp_bindings is not None:
            await self._mcp_bindings.client.close()
            self._mcp_bindings = None

    async def run_turn_stream(self, user_message: str) -> AsyncIterator[AgentEvent]:
        """处理用户一条输入，透传 ReAct 事件，末尾产出 HubTurnCompleteEvent。"""
        message = (user_message or "").strip()
        turn_id = uuid.uuid4().hex[:8]
        set_turn_id(turn_id)
        turn_start = time.monotonic()

        hub_log("turn start", message_len=len(message))

        try:
            if not message:
                hub_log("turn abort", reason="empty_message")
                yield ErrorEvent(error="user_message 不能为空")
                return

            yield HubPhaseEvent(phase="react")
            async for ev in self.react.run_stream(message):
                yield ev

            intent = self.react.get_last_intent()
            if intent is None:
                hub_log("route", route=ROUTE_CLARIFY_ONLY, reason="no_intent")
                outcome = HubTurnOutcome(
                    route=ROUTE_CLARIFY_ONLY,
                    user_reply="",
                    final_user_message="",
                )
                self.last_outcome = outcome
                yield HubTurnCompleteEvent(
                    route=outcome.route,
                    user_reply=outcome.user_reply,
                    final_user_message=outcome.final_user_message,
                )
                return

            user_reply = (intent.user_reply or "").strip()
            hub_log(
                "react done",
                intent=intent.intent,
                is_clear=intent.is_clear,
            )

            if not intent.is_clear:
                route = ROUTE_CLARIFY_ONLY
            else:
                route = ROUTE_DIRECT_REPLY

            hub_log("route", route=route)
            outcome = HubTurnOutcome(
                route=route,
                user_reply=user_reply,
                final_user_message=user_reply,
                intent=intent,
            )
            self.last_outcome = outcome
            hub_log(
                "turn complete",
                route=route,
                final_len=len(user_reply),
                elapsed_ms=int((time.monotonic() - turn_start) * 1000),
            )
            yield HubTurnCompleteEvent(
                route=outcome.route,
                user_reply=outcome.user_reply,
                final_user_message=outcome.final_user_message,
                intent=intent,
            )
        finally:
            clear_turn_id()

    def get_last_outcome(self) -> HubTurnOutcome | None:
        return self.last_outcome
