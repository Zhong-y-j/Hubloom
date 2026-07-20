"""Execute：执行 Think 产出的 tool_calls，写回用的消息交给调用方落库。

不调 LLM、不做上下文裁剪、不碰 MemoryManager。
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from dataclasses import dataclass, field

from core.models import Message, Role, ToolCall
from tools.runner import ToolRunner

from agent.events import AgentEvent, ErrorEvent, ToolCallEvent, ToolResultEvent


@dataclass
class ExecuteResult:
    """一轮 Execute 的写回材料。"""

    messages: list[Message] = field(default_factory=list)
    # (call, result_text, is_error)
    results: list[tuple[ToolCall, str, bool]] = field(default_factory=list)


async def execute(
    tool_calls: list[ToolCall],
    runner: ToolRunner,
    *,
    think_content: str = "",
) -> AsyncIterator[AgentEvent | ExecuteResult]:
    """按序执行 tool_calls。

    流式产出 ``ToolCallEvent`` / ``ToolResultEvent`` / ``ErrorEvent``，
    最后产出 ``ExecuteResult``（1 条 ASSISTANT + N 条 TOOL）。
    """
    if not tool_calls:
        yield ErrorEvent(error="Execute 收到空 tool_calls")
        yield ExecuteResult()
        return

    assistant = Message(
        role=Role.ASSISTANT,
        content=think_content or "",
        tool_calls=list(tool_calls),
    )
    out_messages: list[Message] = [assistant]
    results: list[tuple[ToolCall, str, bool]] = []

    for call in tool_calls:
        args = call.arguments if isinstance(call.arguments, dict) else {}
        yield ToolCallEvent(call_id=call.id, tool_name=call.name, args=args)

        text, is_error = await runner.run(call.name, args)
        text = text if isinstance(text, str) else str(text)

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

    yield ExecuteResult(messages=out_messages, results=results)
