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

from agent.agent_log import agent_trace, clip
from agent.assemble import (
    assemble_respond_a2ui,
    assemble_respond_markdown,
    assemble_think,
    select_think_system,
    turn_has_tool_result,
)
from agent.events import (
    AgentEvent,
    ErrorEvent,
    PhaseEvent,
    RunStatsEvent,
    ToolCallEvent,
    ToolResultEvent,
)
from agent.llm_context_log import dump_llm_context
from agent.loop.execute import ExecuteResult, execute
from agent.loop.respond import (
    PresentMode,
    RespondResult,
    answer_display_parts,
    respond,
    user_visible_content,
)
from agent.loop.think import ThinkDecision, think


@dataclass
class RunResult:
    """一轮 Agent run 的终态（事件流最后一条）。"""

    content: str = ""
    present_mode: PresentMode = "markdown"
    a2ui_messages: list[dict[str, Any]] = field(default_factory=list)
    # 正文与 A2UI 交错段（可选；写入 metadata，不影响 content 列）
    answer_parts: list[dict[str, Any]] = field(default_factory=list)
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
    think_system_after: str | None = None,
) -> AsyncIterator[AgentEvent | RunResult]:
    """执行一整轮 Agent：落库 trigger → Think/Execute 循环 → Respond。

    ``think_system``：工具前提示（含 skills/catalog）。
    ``think_system_after``：工具后短提示；缺省则全程用 ``think_system``。
    """
    started = time.monotonic()
    tool_calls = 0
    tool_errors = 0
    tool_log: list[dict[str, str]] = []
    after_system = (think_system_after or think_system).strip() or think_system

    trigger_text = trigger.content if isinstance(trigger.content, str) else str(trigger.content)
    agent_trace(
        "run start",
        present_mode=present_mode,
        max_think_rounds=max_think_rounds,
        tools=len(tools),
        trigger=clip(trigger_text, 120),
    )

    if present_mode == "auto":
        agent_trace("run abort", reason="auto not implemented")
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
    agent_trace("phase", phase="thinking", present_mode=present_mode)

    for round_i in range(1, max_think_rounds + 1):
        round_started = time.monotonic()
        think_prompt = select_think_system(
            think_system_before=think_system,
            think_system_after=after_system,
            turn_messages=turn_messages,
        )
        agent_trace(
            "think round start",
            round=round_i,
            turn_messages=len(turn_messages),
            think_phase=(
                "after_tools"
                if turn_has_tool_result(turn_messages)
                else "before_tools"
            ),
        )
        messages = await assemble_think(
            memory,
            system_prompt=think_prompt,
            turn_messages=turn_messages,
        )
        dump_llm_context(
            phase="think",
            messages=messages,
            round_i=round_i,
            present_mode=present_mode,
            tools=tools,
        )

        decision: ThinkDecision | None = None
        async for item in think(llm, messages, tools=tools):
            if isinstance(item, AgentEvent):
                yield item
            elif isinstance(item, ThinkDecision):
                decision = item

        if decision is None:
            err = f"Think#{round_i} 未产出 ThinkDecision"
            agent_trace("think round fail", round=round_i, error=err)
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

        route = "execute" if decision.should_execute else "respond"
        tool_names = [tc.name for tc in (decision.tool_calls or [])]
        agent_trace(
            "think round done",
            round=round_i,
            route=route,
            content_len=len(decision.content or ""),
            tool_calls=len(tool_names),
            tools=",".join(tool_names) if tool_names else "-",
            round_ms=_elapsed_ms(round_started),
        )

        if decision.should_execute:
            exec_started = time.monotonic()
            agent_trace(
                "execute start",
                round=round_i,
                tools=",".join(tool_names),
                n=len(tool_names),
            )
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
                agent_trace("execute fail", round=round_i, error=err)
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

            err_n = sum(1 for _, _, is_err in exec_result.results if is_err)
            agent_trace(
                "execute done",
                round=round_i,
                results=len(exec_result.results),
                errors=err_n,
                exec_ms=_elapsed_ms(exec_started),
            )

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
            agent_trace(
                "phase",
                phase="replying",
                present_mode=present_mode,
                round=round_i,
                think_len=len(think_text),
            )

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

            dump_llm_context(
                phase="respond",
                messages=respond_messages,
                round_i=round_i,
                present_mode=present_mode,
            )

            respond_started = time.monotonic()
            agent_trace(
                "respond start",
                round=round_i,
                present_mode=present_mode,
                messages=len(respond_messages),
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
                agent_trace("respond fail", round=round_i, error=err)
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
            parts = answer_display_parts(
                result.content,
                a2ui_messages=a2ui_messages,
            )
            agent_trace(
                "respond done",
                round=round_i,
                present_mode=result.present_mode,
                content_len=len(visible),
                a2ui=len(a2ui_messages),
                answer_parts=len(parts),
                respond_ms=_elapsed_ms(respond_started),
            )
            if visible:
                turn_meta: dict[str, Any] = {"route": present_mode}
                if think_text:
                    turn_meta["thought"] = think_text
                if tool_log:
                    turn_meta["tools"] = tool_log
                if a2ui_messages:
                    turn_meta["a2ui"] = a2ui_messages
                if parts:
                    turn_meta["answer_parts"] = parts
                await _remember(
                    memory,
                    Message(role=Role.ASSISTANT, content=visible),
                    source="agent",
                    metadata=turn_meta,
                )

            agent_trace(
                "run done",
                ok=True,
                think_rounds=round_i,
                tool_calls=tool_calls,
                tool_errors=tool_errors,
                content_len=len(visible),
                elapsed_ms=elapsed,
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
                answer_parts=parts,
                think_rounds=round_i,
                tool_calls=tool_calls,
                tool_errors=tool_errors,
                elapsed_ms=elapsed,
                ok=True,
            )
            return

        err = f"Think#{round_i} 既不 execute 也不 respond"
        agent_trace("run abort", round=round_i, error=err)
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
    agent_trace(
        "run abort",
        error=err,
        think_rounds=max_think_rounds,
        tool_calls=tool_calls,
        tool_errors=tool_errors,
        elapsed_ms=_elapsed_ms(started),
    )
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
