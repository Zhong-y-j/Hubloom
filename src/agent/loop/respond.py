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

from agent.agent_log import agent_trace
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
            agent_trace("respond llm error", present_mode=present_mode, error=str(ev.error)[:200])
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
    agent_trace(
        "respond llm done",
        present_mode=present_mode,
        content_len=len(content),
        a2ui=0,
    )
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


def user_visible_content(
    content: str,
    *,
    a2ui_messages: list[dict[str, Any]] | None = None,
) -> str:
    """供 UI / 历史落库的可见正文：去掉 ``<a2ui-json>``，纯界面时用占位。"""
    text = (content or "").strip()
    if text and has_a2ui_parts(text):
        chunks: list[str] = []
        for part in parse_response(text):
            piece = (getattr(part, "text", None) or "").strip()
            if piece:
                chunks.append(piece)
        text = "\n\n".join(chunks).strip()
    if not text and a2ui_messages:
        return "（交互界面）"
    return text


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
            agent_trace("respond llm error", present_mode=present_mode, error=str(ev.error)[:200])
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
    # present_mode=a2ui 但模型只回了 Markdown：正常降级，不推 error（避免前端标红）
    agent_trace(
        "respond llm done",
        present_mode=present_mode,
        content_len=len(content),
        a2ui=len(a2ui_messages),
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
        agent_trace("respond abort", error="empty messages", present_mode=present_mode)
        yield ErrorEvent(error="Respond 收到空 messages")
        yield RespondResult(present_mode=present_mode)
        return

    agent_trace(
        "respond llm start",
        present_mode=present_mode,
        messages=len(messages),
    )

    if present_mode == "markdown":
        async for item in _stream_markdown(llm, messages, present_mode=present_mode):
            yield item
        return

    if present_mode == "a2ui":
        async for item in _stream_a2ui(llm, messages, present_mode=present_mode):
            yield item
        return

    if present_mode == "auto":
        agent_trace("respond abort", error="auto not implemented")
        yield ErrorEvent(
            error="present_mode='auto' 尚未实现",
            recoverable=False,
        )
        yield RespondResult(present_mode=present_mode)
        return

    agent_trace("respond abort", error=f"unknown present_mode={present_mode!r}")
    yield ErrorEvent(
        error=f"未知 present_mode={present_mode!r}，可选: markdown / a2ui / auto",
        recoverable=False,
    )
    yield RespondResult(present_mode=present_mode)
