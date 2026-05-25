"""PlanExecute 阶段输入输出协议（ReAct → Plan → Reflection handoff）。"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from agents.core.intent import StructuredIntent


class StepStatus(str, Enum):
    """单步执行状态。"""

    PENDING = "pending"
    RUNNING = "running"
    SUCCESS = "success"
    FAILED = "failed"
    SKIPPED = "skipped"


@dataclass
class ExecutionStep:
    """计划中的单步任务。"""

    step_id: int
    agent_type: str
    task_description: str
    expected_output: str = ""
    dependencies: list[int] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "step_id": self.step_id,
            "agent_type": self.agent_type,
            "task_description": self.task_description,
            "expected_output": self.expected_output,
            "dependencies": list(self.dependencies),
        }


@dataclass
class ExecutionPlan:
    """Plan 阶段产出的执行计划。"""

    task_type: str
    steps: list[ExecutionStep] = field(default_factory=list)
    unfulfillable_steps: list[dict[str, Any]] = field(default_factory=list)
    rationale: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "task_type": self.task_type,
            "steps": [s.to_dict() for s in self.steps],
            "unfulfillable_steps": list(self.unfulfillable_steps),
            "rationale": self.rationale,
        }


@dataclass
class SubTaskResult:
    """专业 Agent 单步执行返回（delegate_task 约定）。"""

    success: bool
    content: str = ""
    artifacts: list[str] = field(default_factory=list)
    error: str | None = None
    agent_id: str | None = None
    elapsed_ms: int | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "success": self.success,
            "content": self.content,
            "artifacts": list(self.artifacts),
            "error": self.error,
            "agent_id": self.agent_id,
            "elapsed_ms": self.elapsed_ms,
        }


@dataclass
class ExecutionStepTrace:
    """Execute 阶段单步轨迹。"""

    step_id: int
    agent_type: str
    status: StepStatus
    task_description: str = ""
    agent_id: str | None = None
    output: str = ""
    error: str | None = None
    elapsed_ms: int | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "step_id": self.step_id,
            "agent_type": self.agent_type,
            "status": self.status.value,
            "task_description": self.task_description,
            "agent_id": self.agent_id,
            "output": self.output,
            "error": self.error,
            "elapsed_ms": self.elapsed_ms,
        }


@dataclass
class ExecutionResult:
    """PlanExecute 最终输出（→ Hub / 用户 / 后续 Reflection）。"""

    deliverable: str
    trace: list[ExecutionStepTrace] = field(default_factory=list)
    partial_success: bool = False
    plan: ExecutionPlan | None = None
    source_intent: StructuredIntent | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "deliverable": self.deliverable,
            "trace": [t.to_dict() for t in self.trace],
            "partial_success": self.partial_success,
            "plan": self.plan.to_dict() if self.plan else None,
            "source_intent": (
                self.source_intent.to_dict() if self.source_intent else None
            ),
        }
