"""Respond：面向用户的最终回复（本步仅 Markdown）。

上下文由调用方装配（含 RESPOND_* system）；这里只流式生成正文，不调工具。
``present_mode`` 预留 auto/a2ui；当前仅实现 ``markdown``。
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Literal

from core.models import Message, TokenUsage
from core.provider import (
    DeltaEvent,
    LLMProvider,
    StreamEndEvent,
    StreamErrorEvent,
)

from agent.events import (
    AgentEvent,
    ErrorEvent,
    FinalAnswerDeltaEvent,
    FinalAnswerEvent,
)

PresentMode = Literal["markdown", "a2ui", "auto"]


@dataclass
class RespondResult:
    """一轮 Respond 的终态。"""

    content: str = ""
    present_mode: PresentMode = "markdown"
    usage: TokenUsage | None = None


async def _stream_markdown(
    llm: LLMProvider,
    messages: list[Message],
    *,
    present_mode: PresentMode,
) -> AsyncIterator[AgentEvent | RespondResult]:
    content_parts: list[str] = []
    usage: TokenUsage | None = None

    async for ev in llm.generate_stream(messages=messages, tools=None):
        if isinstance(ev, DeltaEvent):
            if ev.delta:
                content_parts.append(ev.delta)
                yield FinalAnswerDeltaEvent(delta=ev.delta)
        elif isinstance(ev, StreamErrorEvent):
            yield ErrorEvent(error=str(ev.error))
            content = "".join(content_parts)
            yield FinalAnswerEvent(content=content)
            yield RespondResult(content=content, present_mode=present_mode)
            return
        elif isinstance(ev, StreamEndEvent):
            usage = ev.output.usage
            if not content_parts and ev.output.content:
                content_parts.append(ev.output.content)
                yield FinalAnswerDeltaEvent(delta=ev.output.content)
            break

    content = "".join(content_parts).strip()
    yield FinalAnswerEvent(content=content, usage=usage)
    yield RespondResult(content=content, present_mode=present_mode, usage=usage)


async def respond(
    llm: LLMProvider,
    messages: list[Message],
    *,
    present_mode: PresentMode = "markdown",
) -> AsyncIterator[AgentEvent | RespondResult]:
    """基于当前 messages 生成最终用户回复。

    流式产出 ``FinalAnswerDeltaEvent`` / ``ErrorEvent``，
    结束时再产出 ``FinalAnswerEvent`` 与 ``RespondResult``。

    本步：仅 ``markdown`` 已实现；``a2ui`` / ``auto`` 后续补齐。
    """
    if not messages:
        yield ErrorEvent(error="Respond 收到空 messages")
        yield RespondResult(present_mode=present_mode)
        return

    if present_mode == "markdown":
        async for item in _stream_markdown(llm, messages, present_mode=present_mode):
            yield item
        return

    if present_mode == "a2ui":
        yield ErrorEvent(
            error="present_mode='a2ui' 尚未实现",
            recoverable=False,
        )
        yield RespondResult(present_mode=present_mode)
        return

    if present_mode == "auto":
        yield ErrorEvent(
            error="present_mode='auto' 尚未实现",
            recoverable=False,
        )
        yield RespondResult(present_mode=present_mode)
        return

    yield ErrorEvent(
        error=f"未知 present_mode={present_mode!r}，可选: markdown / a2ui / auto",
        recoverable=False,
    )
    yield RespondResult(present_mode=present_mode)
