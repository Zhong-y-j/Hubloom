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
