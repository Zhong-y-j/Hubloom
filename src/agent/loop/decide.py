"""Decide：一轮 LLM → TypedAction。"""

from __future__ import annotations

from collections.abc import AsyncIterator
from dataclasses import dataclass

from core.models import Message, StopReason, ToolCall
from core.provider import (
    DeltaEvent,
    LLMProvider,
    ReasoningDeltaEvent,
    StreamEndEvent,
    StreamErrorEvent,
)

from agent.actions import ActionParseError, TypedAction, parse_decide_output
from agent.agent_log import agent_trace
from agent.events import AgentEvent, ErrorEvent, ThoughtDeltaEvent


@dataclass
class DecideResult:
    action: TypedAction | None = None
    stream_error: str = ""
    parse_error: str = ""

    @property
    def ok(self) -> bool:
        return self.action is not None and not self.stream_error and not self.parse_error


async def decide(
    llm: LLMProvider,
    messages: list[Message],
    *,
    tools: list[dict] | None = None,
) -> AsyncIterator[AgentEvent | DecideResult]:
    if not messages:
        yield ErrorEvent(error="Decide 收到空 messages")
        yield DecideResult(parse_error="empty messages")
        return

    agent_trace("decide start", messages=len(messages), tools=len(tools or []))

    content_parts: list[str] = []
    reasoning_parts: list[str] = []
    tool_calls: list[ToolCall] = []
    stop: StopReason | None = None
    stream_error = ""

    async for ev in llm.generate_stream(messages=messages, tools=tools or None):
        if isinstance(ev, ReasoningDeltaEvent):
            if ev.delta:
                reasoning_parts.append(ev.delta)
                yield ThoughtDeltaEvent(phase="decide", delta=ev.delta)
        elif isinstance(ev, DeltaEvent):
            if ev.delta:
                content_parts.append(ev.delta)
                yield ThoughtDeltaEvent(phase="decide", delta=ev.delta)
        elif isinstance(ev, StreamErrorEvent):
            stream_error = str(ev.error)
            agent_trace("decide stream error", error=stream_error[:200])
            yield ErrorEvent(error=stream_error, recoverable=False)
            yield DecideResult(stream_error=stream_error)
            return
        elif isinstance(ev, StreamEndEvent):
            stop = ev.output.stop_reason
            tool_calls = list(ev.output.tool_calls or [])
            if not content_parts and ev.output.content:
                content_parts.append(ev.output.content)
                yield ThoughtDeltaEvent(phase="decide", delta=ev.output.content)
            thinking = str(getattr(ev.output, "thinking", None) or "").strip()
            if thinking and not reasoning_parts:
                reasoning_parts.append(thinking)
                yield ThoughtDeltaEvent(phase="decide", delta=thinking)
            break

    cleaned = "".join(content_parts).strip()
    reasoning = "".join(reasoning_parts).strip()
    try:
        action = parse_decide_output(
            content=cleaned,
            reasoning_content=reasoning,
            tool_calls=tool_calls,
        )
    except ActionParseError as exc:
        agent_trace("decide parse error", error=str(exc)[:200])
        yield ErrorEvent(error=str(exc), recoverable=True)
        yield DecideResult(parse_error=str(exc))
        return

    agent_trace(
        "decide done",
        kind=action.kind,
        stop=stop.value if stop else None,
        tools=",".join(tc.name for tc in tool_calls) if tool_calls else "",
    )
    yield DecideResult(action=action)
