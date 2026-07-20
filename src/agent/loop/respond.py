"""Respond：面向用户的最终回复（本步仅 Markdown）。

上下文由调用方装配（含 RESPOND_* system）；这里只流式生成正文，不调工具。
``present_mode`` 预留 auto/a2ui；当前仅实现 ``markdown``。
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import Literal, Any

from core.models import Message, TokenUsage
from core.provider import (
    DeltaEvent,
    LLMProvider,
    StreamEndEvent,
    StreamErrorEvent,
)

from agent.events import (
    AgentEvent,
    A2uiMessagesEvent,
    ErrorEvent,
    FinalAnswerDeltaEvent,
    FinalAnswerEvent,
)

from a2ui.parser.parser import has_a2ui_parts, parse_response

PresentMode = Literal["markdown", "a2ui", "auto"]


@dataclass
class RespondResult:
    """一轮 Respond 的终态。"""

    content: str = ""
    present_mode: PresentMode = "markdown"
    a2ui_messages: list[dict[str, Any]] = field(default_factory=list)
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


def _extract_a2ui_messages(content: str) -> list[dict[str, Any]]:
    """从完整回复正文切出 A2UI messages（权威全量）。"""
    if not content or not has_a2ui_parts(content):
        return []
    messages: list[dict[str, Any]] = []
    for part in parse_response(content):
        if part.a2ui_json is None:
            continue
        if isinstance(part.a2ui_json, list):
            messages.extend(m for m in part.a2ui_json if isinstance(m, dict))
        elif isinstance(part.a2ui_json, dict):
            messages.append(part.a2ui_json)
    return messages


async def _stream_a2ui(
    llm: LLMProvider,
    messages: list[Message],
    *,
    present_mode: PresentMode,
) -> AsyncIterator[AgentEvent | RespondResult]:
    """流式生成 A2UI 回复：文本增量 + 结束时权威 A2uiMessagesEvent。"""
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
            a2ui_messages = _extract_a2ui_messages(content)
            if a2ui_messages:
                yield A2uiMessagesEvent(messages=a2ui_messages, replace=True)
            yield FinalAnswerEvent(content=content)
            yield RespondResult(
                content=content,
                present_mode=present_mode,
                a2ui_messages=a2ui_messages,
            )
            return
        elif isinstance(ev, StreamEndEvent):
            usage = ev.output.usage
            if not content_parts and ev.output.content:
                content_parts.append(ev.output.content)
                yield FinalAnswerDeltaEvent(delta=ev.output.content)
            break
    content = "".join(content_parts).strip()
    a2ui_messages = _extract_a2ui_messages(content)
    if a2ui_messages:
        yield A2uiMessagesEvent(messages=a2ui_messages, replace=True)
    elif content:
        # present_mode=a2ui 但模型没吐标签：可告警，仍把正文当最终答案
        yield ErrorEvent(
            error="present_mode='a2ui' 但回复中未找到 <a2ui-json> 块",
            recoverable=True,
        )
    yield FinalAnswerEvent(content=content, usage=usage)
    yield RespondResult(
        content=content,
        present_mode=present_mode,
        a2ui_messages=a2ui_messages,
        usage=usage,
    )


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
        async for item in _stream_a2ui(llm, messages, present_mode=present_mode):
            yield item
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
