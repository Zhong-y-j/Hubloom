"""Present：Think 交班后、Respond 前，判断是否需要 A2UI。

不挂 tools，只读 Think 正文，输出 NEED_A2UI: yes/no。
"""

from __future__ import annotations

import re
from collections.abc import AsyncIterator
from dataclasses import dataclass

from core.models import Message
from core.provider import (
    DeltaEvent,
    LLMProvider,
    StreamEndEvent,
    StreamErrorEvent,
)

from agent.agent_log import agent_trace
from agent.events import AgentEvent, ErrorEvent, PhaseEvent

_NEED_A2UI_RE = re.compile(r"(?im)^\s*NEED_A2UI\s*:\s*(yes|no)\s*$")
_NEED_A2UI_ANY_RE = re.compile(r"(?i)NEED_A2UI\s*:\s*(yes|no)")


def parse_need_a2ui(content: str) -> bool | None:
    """从 Present 输出解析标记；未写则 None。"""
    found: bool | None = None
    for m in _NEED_A2UI_RE.finditer(content or ""):
        found = m.group(1).lower() == "yes"
    if found is not None:
        return found
    # 容错：整段里夹杂标记时取最后一次
    for m in _NEED_A2UI_ANY_RE.finditer(content or ""):
        found = m.group(1).lower() == "yes"
    return found


@dataclass
class PresentDecision:
    """Present 阶段结果。"""

    need_a2ui: bool | None = None
    raw: str = ""


async def present(
    llm: LLMProvider,
    messages: list[Message],
) -> AsyncIterator[AgentEvent | PresentDecision]:
    """基于 Think 正文判断是否需要 A2UI。

    流式仅用于拿完整输出；对外主要关心最终 ``PresentDecision``。
    """
    if not messages:
        agent_trace("present abort", error="empty messages")
        yield ErrorEvent(error="Present 收到空 messages")
        yield PresentDecision(need_a2ui=False)
        return

    yield PhaseEvent(phase="presenting", route="present")
    agent_trace("present llm start", messages=len(messages))

    content_parts: list[str] = []
    async for ev in llm.generate_stream(messages=messages, tools=None):
        if isinstance(ev, DeltaEvent):
            if ev.delta:
                content_parts.append(ev.delta)
        elif isinstance(ev, StreamErrorEvent):
            agent_trace("present llm error", error=str(ev.error)[:200])
            yield ErrorEvent(error=str(ev.error), recoverable=True)
            yield PresentDecision(need_a2ui=False, raw="".join(content_parts))
            return
        elif isinstance(ev, StreamEndEvent):
            if not content_parts and ev.output.content:
                content_parts.append(ev.output.content)
            break

    raw = "".join(content_parts).strip()
    need = parse_need_a2ui(raw)
    # 解析失败时保守：不跑 A2UI，避免误开面板
    resolved = True if need is True else False
    agent_trace(
        "present llm done",
        need_a2ui=resolved,
        parsed=need,
        raw=raw[:80],
    )
    yield PresentDecision(need_a2ui=resolved, raw=raw)
