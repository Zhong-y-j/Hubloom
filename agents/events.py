from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional

from core.models import TokenUsage


class AgentEvent:
    """Agent 层对外事件基类（给 CLI / WebSocket / 前端消费）。"""

    pass


@dataclass
class TextDeltaEvent(AgentEvent):
    """回复文本增量（流式输出用）。"""

    delta: str


@dataclass
class FinalAnswerEvent(AgentEvent):
    """本轮最终回复。

    约定：
    - `content`：给用户看的文本
    - `usage`：Token 使用情况
    - `intent`：结构化意图（ReAct → PlanExecute，可选）
    """

    content: str
    usage: Optional[TokenUsage] = None
    intent: Any = None  # StructuredIntent | None，避免循环 import


@dataclass
class ErrorEvent(AgentEvent):
    """本轮出错（对外以事件表达，而不是直接 raise）。"""

    error: str


# -------- Plan-and-Execute --------
@dataclass
class PlanTextDeltaEvent(AgentEvent):
    """Plan 阶段 LLM 原始输出增量（流式）。"""

    delta: str


@dataclass
class PlanReadyEvent(AgentEvent):
    """Plan 阶段结束，携带解析后的 ExecutionPlan。"""

    plan: Any  # ExecutionPlan


@dataclass
class PlanCreatedEvent(AgentEvent):
    """计划已生成（供 UI 渲染步骤条等）。"""

    steps: list[dict[str, Any]]


@dataclass
class StepStartEvent(AgentEvent):
    """开始执行计划中的某一步。"""

    step_id: int
    description: str
    agent_type: str = ""
    agent_id: str = ""


@dataclass
class StepOutputDeltaEvent(AgentEvent):
    """某一步专业 Agent 产出增量（流式）。"""

    step_id: int
    delta: str


@dataclass
class StepCompleteEvent(AgentEvent):
    """某一步执行结束（含简要结果）。"""

    step_id: int
    summary: str


@dataclass
class StepErrorEvent(AgentEvent):
    """某一步执行异常或提前终止。"""

    step_id: int
    error: str


@dataclass
class ExecutionResultEvent(AgentEvent):
    """PlanExecute 完整执行结果（供 Reflection / Hub）。"""

    result: Any  # ExecutionResult


# -------- Reflection --------
@dataclass
class ReflectionStartEvent(AgentEvent):
    """开始审查 PlanExecute 产出。"""

    step_count: int
    partial_success: bool = False


@dataclass
class ReflectionTextDeltaEvent(AgentEvent):
    """Reflection 阶段 LLM 审查说明增量（流式）。"""

    delta: str


@dataclass
class ReflectionCompleteEvent(AgentEvent):
    """Reflection 结束，携带结构化审查结论（Hub 主消费此事件）。"""

    verdict: Any  # ReflectionVerdict
    elapsed_ms: int = 0


# -------- 以下为 ReAct 专用事件 --------
@dataclass
class ToolCallEvent(AgentEvent):
    """即将调用工具。

    约定：
    - `call_id`：调用 ID
    - `tool_name`：工具名称
    - `args`：工具参数
    """

    call_id: str
    tool_name: str
    args: dict


@dataclass
class ToolResultEvent(AgentEvent):
    """工具执行结果。

    约定：
    - `call_id`：调用 ID
    - `tool_name`：工具名称
    - `result`：工具执行结果
    - `is_error`：是否出错
    """

    call_id: str
    tool_name: str
    result: str
    is_error: bool = False


@dataclass
class RunStatsEvent(AgentEvent):
    """本轮运行统计信息（通常在结束前发出）。"""

    steps: int
    tool_calls: int
    tool_errors: int
    elapsed_ms: int


@dataclass
class IntentOutcomeEvent(AgentEvent):
    """ReAct 阶段结构化意图结果（供 PlanExecute 读取）。"""

    intent: Any  # StructuredIntent
    is_clear: bool

    @property
    def should_invoke_plan(self) -> bool:
        """是否应进入 PlanExecute（委托 intent.should_invoke_plan）。"""
        fn = getattr(self.intent, "should_invoke_plan", None)
        if callable(fn):
            return bool(fn())
        return self.is_clear


@dataclass
class MemoryConsolidatedEvent(AgentEvent):
    """回合结束后长期记忆提炼写入结果。"""

    episodic: list[str]
    semantic: list[str]
    relations: list[str]
    links: list[str] = field(default_factory=list)
    skipped: bool = False
    error: str | None = None


@dataclass
class StageEvent(AgentEvent):
    stage: str  # "initial" | "reflection" | "revise"
