"""Orchestrator：串起 Think ↔ Execute → Respond。

调用方负责：LLM / Memory / ToolRunner / tools / system 文案。
这里只做循环、落库、事件透传与按 present_mode 装配 Respond。
"""

from __future__ import annotations

import json
import time
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import Any

from core.models import Message, Role
from core.provider import LLMProvider
from memory.manager import MemoryManager
from tools.runner import ToolRunner

from agent.assemble import (
    assemble_respond_a2ui,
    assemble_respond_markdown,
    assemble_think,
)
from agent.events import (
    AgentEvent,
    ErrorEvent,
    PhaseEvent,
    RunStatsEvent,
    ToolCallEvent,
    ToolResultEvent,
)
from agent.loop.execute import ExecuteResult, execute
from agent.loop.respond import PresentMode, RespondResult, respond, user_visible_content
from agent.loop.think import ThinkDecision, think


@dataclass
class RunResult:
    """一轮 Agent run 的终态（事件流最后一条）。"""

    content: str = ""
    present_mode: PresentMode = "markdown"
    a2ui_messages: list[dict[str, Any]] = field(default_factory=list)
    think_rounds: int = 0
    tool_calls: int = 0
    tool_errors: int = 0
    elapsed_ms: int = 0
    ok: bool = True
    error: str = ""


async def _remember(
    memory: MemoryManager,
    message: Message,
    *,
    source: str = "agent",
    metadata: dict[str, Any] | None = None,
) -> None:
    await memory.remember(
        memory_type="conversation",
        message=message,
        source=source,
        metadata=metadata,
    )


def _elapsed_ms(started: float) -> int:
    return max(0, int((time.monotonic() - started) * 1000))


def _append_tool_log(
    tool_log: list[dict[str, str]],
    ev: ToolCallEvent | ToolResultEvent,
) -> None:
    if isinstance(ev, ToolCallEvent):
        tool_log.append(
            {
                "title": f"调用 · {ev.tool_name}",
                "body": json.dumps(ev.args or {}, ensure_ascii=False, indent=2),
            }
        )
        return
    prefix = "失败 · " if ev.is_error else "返回 · "
    tool_log.append(
        {
            "title": f"{prefix}{ev.tool_name}",
            "body": (ev.result or "")[:4000],
        }
    )


async def run_stream(
    *,
    llm: LLMProvider,
    memory: MemoryManager,
    runner: ToolRunner,
    tools: list[dict[str, Any]],
    trigger: Message,
    think_system: str,
    respond_system: str,
    present_mode: PresentMode = "markdown",
    max_think_rounds: int = 5,
    trigger_source: str = "user",
) -> AsyncIterator[AgentEvent | RunResult]:
    """执行一整轮 Agent：落库 trigger → Think/Execute 循环 → Respond。

    事件顺序大致为：
    PhaseEvent(thinking) → … → PhaseEvent(replying) → …
    → RunStatsEvent → RunResult
    """
    started = time.monotonic()
    tool_calls = 0
    tool_errors = 0
    tool_log: list[dict[str, str]] = []

    if present_mode == "auto":
        yield ErrorEvent(
            error="present_mode='auto' 尚未实现",
            recoverable=False,
        )
        elapsed = _elapsed_ms(started)
        yield RunStatsEvent(
            steps=0,
            tool_calls=0,
            tool_errors=0,
            elapsed_ms=elapsed,
        )
        yield RunResult(
            present_mode=present_mode,
            elapsed_ms=elapsed,
            ok=False,
            error="auto not implemented",
        )
        return

    turn_messages: list[Message] = [trigger]
    await _remember(memory, trigger, source=trigger_source)

    yield PhaseEvent(phase="thinking", route=present_mode)

    for round_i in range(1, max_think_rounds + 1):
        messages = await assemble_think(
            memory,
            system_prompt=think_system,
            turn_messages=turn_messages,
        )

        decision: ThinkDecision | None = None
        async for item in think(llm, messages, tools=tools):
            if isinstance(item, AgentEvent):
                yield item
            elif isinstance(item, ThinkDecision):
                decision = item

        if decision is None:
            err = f"Think#{round_i} 未产出 ThinkDecision"
            elapsed = _elapsed_ms(started)
            yield ErrorEvent(error=err, recoverable=False)
            yield RunStatsEvent(
                steps=round_i,
                tool_calls=tool_calls,
                tool_errors=tool_errors,
                elapsed_ms=elapsed,
            )
            yield RunResult(
                present_mode=present_mode,
                think_rounds=round_i,
                tool_calls=tool_calls,
                tool_errors=tool_errors,
                elapsed_ms=elapsed,
                ok=False,
                error=err,
            )
            return

        if decision.should_execute:
            exec_result: ExecuteResult | None = None
            async for item in execute(
                decision.tool_calls,
                runner,
                think_content=decision.content,
            ):
                if isinstance(item, ToolCallEvent):
                    tool_calls += 1
                    _append_tool_log(tool_log, item)
                    yield item
                elif isinstance(item, ToolResultEvent):
                    if item.is_error:
                        tool_errors += 1
                    _append_tool_log(tool_log, item)
                    yield item
                elif isinstance(item, AgentEvent):
                    yield item
                elif isinstance(item, ExecuteResult):
                    exec_result = item

            if exec_result is None:
                err = f"Think#{round_i} 后 Execute 未产出 ExecuteResult"
                elapsed = _elapsed_ms(started)
                yield ErrorEvent(error=err, recoverable=False)
                yield RunStatsEvent(
                    steps=round_i,
                    tool_calls=tool_calls,
                    tool_errors=tool_errors,
                    elapsed_ms=elapsed,
                )
                yield RunResult(
                    present_mode=present_mode,
                    think_rounds=round_i,
                    tool_calls=tool_calls,
                    tool_errors=tool_errors,
                    elapsed_ms=elapsed,
                    ok=False,
                    error=err,
                )
                return

            for msg in exec_result.messages:
                meta: dict[str, Any] | None = None
                if msg.role == Role.ASSISTANT and msg.tool_calls:
                    meta = {"display": False}
                await _remember(memory, msg, source="agent", metadata=meta)
                turn_messages.append(msg)
            continue

        if decision.should_respond:
            think_text = (decision.content or "").strip()
            think_msg = Message(role=Role.ASSISTANT, content=think_text)
            # 思考过程进库供多轮 recall，但不进历史 UI
            await _remember(
                memory,
                think_msg,
                source="agent",
                metadata={"display": False},
            )
            turn_messages.append(think_msg)

            yield PhaseEvent(phase="replying", route=present_mode)

            if present_mode == "a2ui":
                respond_messages = assemble_respond_a2ui(
                    system_prompt=respond_system,
                    think_content=think_text,
                )
            else:
                respond_messages = assemble_respond_markdown(
                    system_prompt=respond_system,
                    think_content=think_text,
                )

            result: RespondResult | None = None
            async for item in respond(
                llm,
                respond_messages,
                present_mode=present_mode,
            ):
                if isinstance(item, AgentEvent):
                    yield item
                elif isinstance(item, RespondResult):
                    result = item

            elapsed = _elapsed_ms(started)

            if result is None:
                err = "Respond 未产出 RespondResult"
                yield ErrorEvent(error=err, recoverable=False)
                yield RunStatsEvent(
                    steps=round_i,
                    tool_calls=tool_calls,
                    tool_errors=tool_errors,
                    elapsed_ms=elapsed,
                )
                yield RunResult(
                    present_mode=present_mode,
                    think_rounds=round_i,
                    tool_calls=tool_calls,
                    tool_errors=tool_errors,
                    elapsed_ms=elapsed,
                    ok=False,
                    error=err,
                )
                return

            a2ui_messages = list(result.a2ui_messages or [])
            visible = user_visible_content(
                result.content,
                a2ui_messages=a2ui_messages,
            )
            if visible:
                turn_meta: dict[str, Any] = {"route": present_mode}
                if think_text:
                    turn_meta["thought"] = think_text
                if tool_log:
                    turn_meta["tools"] = tool_log
                if a2ui_messages:
                    turn_meta["a2ui"] = a2ui_messages
                await _remember(
                    memory,
                    Message(role=Role.ASSISTANT, content=visible),
                    source="agent",
                    metadata=turn_meta,
                )

            yield RunStatsEvent(
                steps=round_i,
                tool_calls=tool_calls,
                tool_errors=tool_errors,
                elapsed_ms=elapsed,
            )
            yield RunResult(
                content=visible,
                present_mode=result.present_mode,
                a2ui_messages=a2ui_messages,
                think_rounds=round_i,
                tool_calls=tool_calls,
                tool_errors=tool_errors,
                elapsed_ms=elapsed,
                ok=True,
            )
            return

        err = f"Think#{round_i} 既不 execute 也不 respond"
        elapsed = _elapsed_ms(started)
        yield ErrorEvent(error=err, recoverable=False)
        yield RunStatsEvent(
            steps=round_i,
            tool_calls=tool_calls,
            tool_errors=tool_errors,
            elapsed_ms=elapsed,
        )
        yield RunResult(
            present_mode=present_mode,
            think_rounds=round_i,
            tool_calls=tool_calls,
            tool_errors=tool_errors,
            elapsed_ms=elapsed,
            ok=False,
            error=err,
        )
        return

    err = f"达到 Think 轮次上限 {max_think_rounds}，未进入 Respond"
    elapsed = _elapsed_ms(started)
    yield ErrorEvent(error=err, recoverable=False)
    yield RunStatsEvent(
        steps=max_think_rounds,
        tool_calls=tool_calls,
        tool_errors=tool_errors,
        elapsed_ms=elapsed,
    )
    yield RunResult(
        present_mode=present_mode,
        think_rounds=max_think_rounds,
        tool_calls=tool_calls,
        tool_errors=tool_errors,
        elapsed_ms=elapsed,
        ok=False,
        error=err,
    )
