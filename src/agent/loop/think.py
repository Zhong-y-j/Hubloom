"""Think：读已装配好的会话上下文，决定「继续调工具」还是「去 Respond」。

上下文工程（历史裁剪、本轮工具结果保留等）在调用本函数之前完成；
这里只做一轮 LLM 决策。Execute 写回历史后，再次调用即可做「工具后的思考」。

Think 不执行工具，只接收工具定义（``tools=``），供模型选择是否发起 tool_calls。
呈现（要不要 A2UI）由单独的 Present 阶段决定，不在此处标记。
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from dataclasses import dataclass, field

from core.models import Message, StopReason, ToolCall
from core.provider import (
    DeltaEvent,
    LLMProvider,
    ReasoningDeltaEvent,
    StreamEndEvent,
    StreamErrorEvent,
)

from agent.agent_log import agent_trace
from agent.events import AgentEvent, ErrorEvent, ThoughtDeltaEvent


@dataclass
class ThinkDecision:
    """一轮 Think 的路由结果。"""

    content: str = ""
    tool_calls: list[ToolCall] = field(default_factory=list)

    @property
    def should_execute(self) -> bool:
        """需要进入 Execute。"""
        return bool(self.tool_calls)

    @property
    def should_respond(self) -> bool:
        """可以进入 Respond（不再调工具）。"""
        return not self.should_execute


async def think(
    llm: LLMProvider,
    messages: list[Message],
    *,
    tools: list[dict] | None = None,
) -> AsyncIterator[AgentEvent | ThinkDecision]:
    """基于当前 messages 思考一轮。

    流式产出 ``ThoughtDeltaEvent`` / ``ErrorEvent``，最后产出 ``ThinkDecision``。

    - ``decision.should_execute`` → 交给 Execute，写回历史后再 ``think(...)``
    - ``decision.should_respond`` → 交给 Present（auto）/ Respond
    """
    if not messages:
        agent_trace("think abort", error="empty messages")
        yield ErrorEvent(error="Think 收到空 messages")
        yield ThinkDecision()
        return

    agent_trace(
        "think llm start",
        messages=len(messages),
        tools=len(tools or []),
    )

    content_parts: list[str] = []
    tool_calls: list[ToolCall] = []
    stop: StopReason | None = None

    async for ev in llm.generate_stream(
        messages=messages,
        tools=tools or None,
    ):
        if isinstance(ev, ReasoningDeltaEvent):
            if ev.delta:
                content_parts.append(ev.delta)
                yield ThoughtDeltaEvent(phase="think", delta=ev.delta)
        elif isinstance(ev, DeltaEvent):
            if ev.delta:
                content_parts.append(ev.delta)
                yield ThoughtDeltaEvent(phase="think", delta=ev.delta)
        elif isinstance(ev, StreamErrorEvent):
            agent_trace("think llm error", error=str(ev.error)[:200])
            yield ErrorEvent(error=str(ev.error))
            yield ThinkDecision(content="".join(content_parts).strip())
            return
        elif isinstance(ev, StreamEndEvent):
            stop = ev.output.stop_reason
            tool_calls = list(ev.output.tool_calls or [])
            if not content_parts and ev.output.content:
                content_parts.append(ev.output.content)
                yield ThoughtDeltaEvent(phase="think", delta=ev.output.content)
            if not content_parts and getattr(ev.output, "thinking", None):
                thinking = str(ev.output.thinking or "")
                if thinking:
                    content_parts.append(thinking)
                    yield ThoughtDeltaEvent(phase="think", delta=thinking)
            break

    cleaned = "".join(content_parts).strip()
    if stop == StopReason.TOOL_CALLS and tool_calls:
        agent_trace(
            "think llm done",
            route="execute",
            stop=stop.value if stop else None,
            content_len=len(cleaned),
            tool_calls=len(tool_calls),
            tools=",".join(tc.name for tc in tool_calls),
        )
        yield ThinkDecision(content=cleaned, tool_calls=tool_calls)
    else:
        agent_trace(
            "think llm done",
            route="respond",
            stop=stop.value if stop else None,
            content_len=len(cleaned),
            tool_calls=0,
        )
        yield ThinkDecision(content=cleaned, tool_calls=[])
