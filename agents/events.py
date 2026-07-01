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
    - `content`：回复内容
    - `usage`：Token 使用情况
    """

    content: str
    usage: Optional[TokenUsage] = None


@dataclass
class ErrorEvent(AgentEvent):
    """本轮出错（对外以事件表达，而不是直接 raise）。"""

    error: str


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
