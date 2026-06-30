"""Hub 编排层输入输出。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from agents.core.intent import StructuredIntent

ROUTE_CLARIFY_ONLY = "clarify_only"
ROUTE_DIRECT_REPLY = "direct_reply"


@dataclass
class HubTurnOutcome:
    """一轮 ``run_turn_stream`` 结束后的汇总（供日志 / API）。"""

    route: str
    user_reply: str = ""
    final_user_message: str | None = None
    intent: StructuredIntent | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "route": self.route,
            "user_reply": self.user_reply,
            "final_user_message": self.final_user_message,
            "intent": self.intent.to_dict() if self.intent else None,
        }
