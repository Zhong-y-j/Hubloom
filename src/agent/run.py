"""Orchestrator：串起 Think ↔ Execute → Respond。

调用方负责：LLM / Memory / ToolRunner / tools / system 文案。
这里只做循环、落库、事件透传与按 present_mode 装配 Respond。
"""

from __future__ import annotations

import asyncio
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


def resolve_respond_mode(
    requested: PresentMode,
    need_a2ui: bool | None,
) -> PresentMode:
    """兼容旧语义：auto + need → a2ui，否则 markdown；强制模式原样返回。

    新逻辑请用 ``plan_respond_passes``（auto 可 Markdown+A2UI 两段）。
    """
    if requested == "auto":
        return "a2ui" if need_a2ui is True else "markdown"
    return requested


@dataclass(frozen=True)
class RespondPassPlan:
    """本轮要跑哪些 Respond。"""

    run_markdown: bool
    run_a2ui: bool

    @property
    def result_present_mode(self) -> PresentMode:
        if self.run_markdown and self.run_a2ui:
            return "auto"
        if self.run_a2ui:
            return "a2ui"
        return "markdown"


def plan_respond_passes(
    requested: PresentMode,
    need_a2ui: bool | None,
) -> RespondPassPlan:
    """决定本轮 Respond 跑哪些通道。

    - ``markdown``：只 Markdown
    - ``a2ui``：只 A2UI（强制）
    - ``auto``：Markdown **始终**有；``NEED_A2UI: yes`` 时再追加 A2UI（可并行）
    """
    if requested == "markdown":
        return RespondPassPlan(run_markdown=True, run_a2ui=False)
    if requested == "a2ui":
        return RespondPassPlan(run_markdown=False, run_a2ui=True)
    # auto
    return RespondPassPlan(
        run_markdown=True,
        run_a2ui=(need_a2ui is True),
    )


async def _pump_respond(
    llm: LLMProvider,
    messages: list[Message],
    *,
    present_mode: PresentMode,
    queue: asyncio.Queue[tuple[str, PresentMode, Any]],
) -> None:
    """把一轮 respond 的事件推进共享队列，供并行合并下发。"""
    try:
        result: RespondResult | None = None
        async for item in respond(llm, messages, present_mode=present_mode):
            if isinstance(item, AgentEvent):
                await queue.put(("event", present_mode, item))
            elif isinstance(item, RespondResult):
                result = item
        await queue.put(("done", present_mode, result))
    except Exception as exc:  # noqa: BLE001 — 并行泵需把异常带回主循环
        await queue.put(("error", present_mode, exc))


async def run_stream(
    *,
    llm: LLMProvider,
    memory: MemoryManager,
    runner: ToolRunner,
    tools: list[dict[str, Any]],
    trigger: Message,
    think_system: str,
    respond_markdown_system: str,
    respond_a2ui_system: str,
    present_mode: PresentMode = "markdown",
    max_think_rounds: int = 5,
    trigger_source: str = "user",
    think_system_after: str | None = None,
) -> AsyncIterator[AgentEvent | RunResult]:
    """执行一整轮 Agent：落库 trigger → Think/Execute 循环 → Respond。

    ``think_system``：工具前提示（含 skills/catalog）。
    ``think_system_after``：工具后短提示；缺省则全程用 ``think_system``。
    ``present_mode=auto``：由 Think 的 NEED_A2UI 标记选择 Markdown / A2UI Respond。
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
            need_a2ui=decision.need_a2ui,
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

            plan = plan_respond_passes(present_mode, decision.need_a2ui)
            agent_trace(
                "respond plan",
                requested=present_mode,
                need_a2ui=decision.need_a2ui,
                run_markdown=plan.run_markdown,
                run_a2ui=plan.run_a2ui,
                parallel=bool(plan.run_markdown and plan.run_a2ui),
                round=round_i,
                think_len=len(think_text),
            )

            respond_started = time.monotonic()
            md_result: RespondResult | None = None
            a2ui_result: RespondResult | None = None

            md_messages = None
            a2ui_messages_ctx = None
            if plan.run_markdown:
                md_messages = assemble_respond_markdown(
                    system_prompt=respond_markdown_system,
                    think_content=think_text,
                )
                dump_llm_context(
                    phase="respond",
                    messages=md_messages,
                    round_i=round_i,
                    present_mode="markdown",
                )
            if plan.run_a2ui:
                a2ui_messages_ctx = assemble_respond_a2ui(
                    system_prompt=respond_a2ui_system,
                    think_content=think_text,
                )
                dump_llm_context(
                    phase="respond",
                    messages=a2ui_messages_ctx,
                    round_i=round_i,
                    present_mode="a2ui",
                )

            # 两段都要：并行泵事件；只要一段：串行即可
            if plan.run_markdown and plan.run_a2ui:
                yield PhaseEvent(phase="replying", route="auto")
                agent_trace(
                    "respond start",
                    round=round_i,
                    present_mode="auto",
                    parallel=True,
                )
                queue: asyncio.Queue[tuple[str, PresentMode, Any]] = asyncio.Queue()
                tasks = [
                    asyncio.create_task(
                        _pump_respond(
                            llm,
                            md_messages,  # type: ignore[arg-type]
                            present_mode="markdown",
                            queue=queue,
                        )
                    ),
                    asyncio.create_task(
                        _pump_respond(
                            llm,
                            a2ui_messages_ctx,  # type: ignore[arg-type]
                            present_mode="a2ui",
                            queue=queue,
                        )
                    ),
                ]
                pending = len(tasks)
                pump_error: str | None = None
                try:
                    while pending:
                        kind, mode, payload = await queue.get()
                        if kind == "event":
                            yield payload
                        elif kind == "done":
                            if mode == "markdown":
                                md_result = payload
                            else:
                                a2ui_result = payload
                            pending -= 1
                        elif kind == "error":
                            pump_error = f"{mode} Respond 失败: {payload}"
                            pending -= 1
                finally:
                    for t in tasks:
                        if not t.done():
                            t.cancel()
                    await asyncio.gather(*tasks, return_exceptions=True)

                if pump_error:
                    agent_trace("respond fail", round=round_i, error=pump_error)
                    elapsed = _elapsed_ms(started)
                    yield ErrorEvent(error=pump_error, recoverable=False)
                    yield RunStatsEvent(
                        steps=round_i,
                        tool_calls=tool_calls,
                        tool_errors=tool_errors,
                        elapsed_ms=elapsed,
                    )
                    yield RunResult(
                        present_mode=plan.result_present_mode,
                        think_rounds=round_i,
                        tool_calls=tool_calls,
                        tool_errors=tool_errors,
                        elapsed_ms=elapsed,
                        ok=False,
                        error=pump_error,
                    )
                    return
                if md_result is None or a2ui_result is None:
                    err = "并行 Respond 未完整产出 Markdown/A2UI 结果"
                    agent_trace("respond fail", round=round_i, error=err)
                    elapsed = _elapsed_ms(started)
                    yield ErrorEvent(error=err, recoverable=False)
                    yield RunStatsEvent(
                        steps=round_i,
                        tool_calls=tool_calls,
                        tool_errors=tool_errors,
                        elapsed_ms=elapsed,
                    )
                    yield RunResult(
                        present_mode=plan.result_present_mode,
                        think_rounds=round_i,
                        tool_calls=tool_calls,
                        tool_errors=tool_errors,
                        elapsed_ms=elapsed,
                        ok=False,
                        error=err,
                    )
                    return
            else:
                if plan.run_markdown and md_messages is not None:
                    yield PhaseEvent(phase="replying", route="markdown")
                    agent_trace(
                        "respond start",
                        round=round_i,
                        present_mode="markdown",
                        messages=len(md_messages),
                    )
                    async for item in respond(
                        llm,
                        md_messages,
                        present_mode="markdown",
                    ):
                        if isinstance(item, AgentEvent):
                            yield item
                        elif isinstance(item, RespondResult):
                            md_result = item
                    if md_result is None:
                        err = "Markdown Respond 未产出 RespondResult"
                        agent_trace("respond fail", round=round_i, error=err)
                        elapsed = _elapsed_ms(started)
                        yield ErrorEvent(error=err, recoverable=False)
                        yield RunStatsEvent(
                            steps=round_i,
                            tool_calls=tool_calls,
                            tool_errors=tool_errors,
                            elapsed_ms=elapsed,
                        )
                        yield RunResult(
                            present_mode="markdown",
                            think_rounds=round_i,
                            tool_calls=tool_calls,
                            tool_errors=tool_errors,
                            elapsed_ms=elapsed,
                            ok=False,
                            error=err,
                        )
                        return

                if plan.run_a2ui and a2ui_messages_ctx is not None:
                    yield PhaseEvent(phase="replying", route="a2ui")
                    agent_trace(
                        "respond start",
                        round=round_i,
                        present_mode="a2ui",
                        messages=len(a2ui_messages_ctx),
                    )
                    async for item in respond(
                        llm,
                        a2ui_messages_ctx,
                        present_mode="a2ui",
                    ):
                        if isinstance(item, AgentEvent):
                            yield item
                        elif isinstance(item, RespondResult):
                            a2ui_result = item
                    if a2ui_result is None:
                        err = "A2UI Respond 未产出 RespondResult"
                        agent_trace("respond fail", round=round_i, error=err)
                        elapsed = _elapsed_ms(started)
                        yield ErrorEvent(error=err, recoverable=False)
                        yield RunStatsEvent(
                            steps=round_i,
                            tool_calls=tool_calls,
                            tool_errors=tool_errors,
                            elapsed_ms=elapsed,
                        )
                        yield RunResult(
                            present_mode=plan.result_present_mode,
                            think_rounds=round_i,
                            tool_calls=tool_calls,
                            tool_errors=tool_errors,
                            elapsed_ms=elapsed,
                            ok=False,
                            error=err,
                        )
                        return

            elapsed = _elapsed_ms(started)
            result_mode = plan.result_present_mode

            # 长期正文以 Markdown 为准；A2UI 进 metadata
            md_visible = ""
            if md_result is not None:
                md_visible = user_visible_content(md_result.content)
            a2ui_messages = list(
                (a2ui_result.a2ui_messages if a2ui_result else None) or []
            )
            a2ui_visible = ""
            if a2ui_result is not None:
                a2ui_visible = user_visible_content(
                    a2ui_result.content,
                    a2ui_messages=a2ui_messages,
                )
                if a2ui_visible == "（交互界面）":
                    a2ui_visible = ""

            visible = md_visible or a2ui_visible
            parts: list[dict[str, Any]] = []
            if md_visible:
                parts.append({"type": "text", "text": md_visible})
            if a2ui_messages:
                parts.append({"type": "a2ui"})
            if a2ui_visible and a2ui_visible != md_visible:
                parts.append({"type": "text", "text": a2ui_visible})

            agent_trace(
                "respond done",
                round=round_i,
                present_mode=result_mode,
                content_len=len(visible),
                a2ui=len(a2ui_messages),
                answer_parts=len(parts),
                respond_ms=_elapsed_ms(respond_started),
            )
            if visible or a2ui_messages:
                turn_meta: dict[str, Any] = {
                    "route": result_mode,
                    "requested_present_mode": present_mode,
                }
                if decision.need_a2ui is not None:
                    turn_meta["need_a2ui"] = decision.need_a2ui
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
                    Message(
                        role=Role.ASSISTANT,
                        content=visible or "（交互界面）",
                    ),
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
                present_mode=result_mode,
                elapsed_ms=elapsed,
            )
            yield RunStatsEvent(
                steps=round_i,
                tool_calls=tool_calls,
                tool_errors=tool_errors,
                elapsed_ms=elapsed,
            )
            yield RunResult(
                content=visible or "（交互界面）",
                present_mode=result_mode,
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
