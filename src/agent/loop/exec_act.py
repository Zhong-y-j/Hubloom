"""Exec：执行业务 Act（ToolRunner）。"""

from __future__ import annotations

from collections.abc import AsyncIterator
from dataclasses import dataclass, field

from core.models import Message, Role, ToolCall
from tools.runner import ToolRunner

from agent.agent_log import agent_trace, clip
from agent.events import AgentEvent, ErrorEvent, ToolCallEvent, ToolResultEvent


@dataclass
class ExecResult:
    messages: list[Message] = field(default_factory=list)
    results: list[tuple[ToolCall, str, bool]] = field(default_factory=list)


async def exec_acts(
    tool_calls: list[ToolCall],
    runner: ToolRunner,
    *,
    assistant_content: str = "",
    reasoning_content: str = "",
) -> AsyncIterator[AgentEvent | ExecResult]:
    if not tool_calls:
        yield ErrorEvent(error="Exec 收到空 tool_calls")
        yield ExecResult()
        return

    assistant = Message(
        role=Role.ASSISTANT,
        content=assistant_content or "",
        tool_calls=list(tool_calls),
        reasoning_content=(reasoning_content or None),
    )
    out_messages: list[Message] = [assistant]
    results: list[tuple[ToolCall, str, bool]] = []

    for call in tool_calls:
        args = call.arguments if isinstance(call.arguments, dict) else {}
        agent_trace("exec act", tool=call.name, call_id=call.id)
        yield ToolCallEvent(call_id=call.id, tool_name=call.name, args=args)

        text, is_error = await runner.run(call.name, args)
        text = text if isinstance(text, str) else str(text)

        agent_trace(
            "exec result",
            tool=call.name,
            is_error=is_error,
            preview=clip(text, 160),
        )
        yield ToolResultEvent(
            call_id=call.id,
            tool_name=call.name,
            result=text,
            is_error=is_error,
        )
        out_messages.append(
            Message(
                role=Role.TOOL,
                content=text,
                tool_call_id=call.id,
                name=call.name,
            )
        )
        results.append((call, text, is_error))

    yield ExecResult(messages=out_messages, results=results)
