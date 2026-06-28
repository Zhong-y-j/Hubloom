"""Hub 编排层输入输出。"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from agents.core.intent import StructuredIntent
from agents.plan.models import ExecutionResult
from agents.reflection.models import ReflectionVerdict

# Hub 路由结果（一轮用户输入）
ROUTE_CLARIFY_ONLY = "clarify_only"
ROUTE_PLAN_READINESS_CLARIFY = "plan_readiness_clarify"
ROUTE_DIRECT_REPLY = "direct_reply"
ROUTE_PLAN_EXECUTE = "plan_execute"
ROUTE_PLAN_REFLECT = "plan_reflect"
ROUTE_PLAN_REVISE = "plan_revise"
ROUTE_PLAN_REVISE_REFLECT = "plan_revise_reflect"


@dataclass
class HubTurnOutcome:
    """一轮 ``run_turn_stream`` 结束后的汇总（供日志 / API）。"""

    route: str
    user_reply: str = ""
    deliverable: str | None = None
    delivery_summary: str | None = None
    final_user_message: str | None = None
    intent: StructuredIntent | None = None
    execution_result: ExecutionResult | None = None
    reflection_verdict: ReflectionVerdict | None = None
    revision_rounds: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "route": self.route,
            "user_reply": self.user_reply,
            "deliverable": self.deliverable,
            "delivery_summary": self.delivery_summary,
            "final_user_message": self.final_user_message,
            "intent": self.intent.to_dict() if self.intent else None,
            "execution_result": (
                self.execution_result.to_dict() if self.execution_result else None
            ),
            "reflection_verdict": (
                self.reflection_verdict.to_dict()
                if self.reflection_verdict
                else None
            ),
            "revision_rounds": self.revision_rounds,
        }
