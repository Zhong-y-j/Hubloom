"""Agent 对外事件（无 A2UI）。"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional

from core.models import TokenUsage


class AgentEvent:
    """Agent 层对外事件基类。"""


@dataclass
class TextDeltaEvent(AgentEvent):
    delta: str


@dataclass
class ThoughtDeltaEvent(AgentEvent):
    phase: str
    delta: str


@dataclass
class FinalAnswerEvent(AgentEvent):
    content: str
    usage: Optional[TokenUsage] = None


@dataclass
class ErrorEvent(AgentEvent):
    error: str
    recoverable: bool = False


@dataclass
class ToolCallEvent(AgentEvent):
    call_id: str
    tool_name: str
    args: dict[str, Any]


@dataclass
class ToolResultEvent(AgentEvent):
    call_id: str
    tool_name: str
    result: str
    is_error: bool = False
    journal_id: str = ""


@dataclass
class RemoteProcessEvent(AgentEvent):
    """出站委托过程增量（A2A / UI）。"""

    call_id: str
    agent_id: str
    channel: str
    delta: str = ""
    status: str = ""


@dataclass
class PhaseEvent(AgentEvent):
    phase: str
    route: str = ""


@dataclass
class StepEvent(AgentEvent):
    """一轮 Decide 已选定 Typed 动作。"""

    step: int
    action: str
    journal_ids: list[str] = field(default_factory=list)


@dataclass
class RunCompleteEvent(AgentEvent):
    """Run 终态（与 RunResult 对齐；宿主可只订阅事件）。"""

    status: str
    content: str = ""
    ok: bool = True
    journal_run_id: str = ""
    evidence_ids: list[str] = field(default_factory=list)
    error: str = ""


@dataclass
class RunStatsEvent(AgentEvent):
    steps: int
    tool_calls: int
    tool_errors: int
    elapsed_ms: int
