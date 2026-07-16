from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional

from core.models import TokenUsage


class AgentEvent:
    """Agent 层对外事件基类（给 CLI / WebSocket / 前端消费）。"""

    pass


@dataclass
class TextDeltaEvent(AgentEvent):
    """回复文本增量（流式输出用，简单路径直答等场景）。"""

    delta: str


@dataclass
class ThoughtDeltaEvent(AgentEvent):
    """思考过程区流式文本（deliberate / execute / replan 阶段）。"""

    phase: str
    delta: str


@dataclass
class FinalAnswerEvent(AgentEvent):
    """本轮最终回复（结果区结束信号）。

    约定：
    - `content`：完整回复内容
    - `usage`：Token 使用情况
    """

    content: str
    usage: Optional[TokenUsage] = None


@dataclass
class FinalAnswerDeltaEvent(AgentEvent):
    """最终结果区流式文本增量（仅 respond 阶段）。"""

    delta: str


@dataclass
class A2uiMessagesEvent(AgentEvent):
    """从最终回复中切出的 A2UI 消息数组（结果区，非流式整包下发）。"""

    messages: list[dict[str, Any]]


@dataclass
class ErrorEvent(AgentEvent):
    """本轮出错（对外以事件表达，而不是直接 raise）。"""

    error: str
    recoverable: bool = False


@dataclass
class ToolCallEvent(AgentEvent):
    """即将调用工具（思考过程区）。"""

    call_id: str
    tool_name: str
    args: dict


@dataclass
class ToolResultEvent(AgentEvent):
    """工具执行结果（思考过程区）。"""

    call_id: str
    tool_name: str
    result: str
    is_error: bool = False


@dataclass
class RemoteProcessEvent(AgentEvent):
    """出站委托时远程 Agent 的过程增量（仅 UI / SSE，不进 LLM tool_result）。"""

    call_id: str
    agent_id: str
    channel: str  # status | trace | answer
    delta: str = ""
    status: str = ""  # working | completed | failed | started


@dataclass
class PhaseEvent(AgentEvent):
    """编排阶段切换（供前端展示 Agent 状态）。"""

    phase: str  # thinking | replying
    route: str = ""


@dataclass
class RunStatsEvent(AgentEvent):
    """本轮运行统计信息（通常在结束前发出）。"""

    steps: int
    tool_calls: int
    tool_errors: int
    elapsed_ms: int
