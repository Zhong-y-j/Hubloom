"""Orchestrator：Policy-Bounded Typed ReAct 单环（Step 2：Journal）。

Decide → Act|Ask|AwaitConfirm|Finish；观察入 Evidence Journal；无 A2UI。
Ask/Confirm 本步仍结束本轮（waiting_user）；Wait Profile 见后续 Step。
本模块不依赖 HubloomRuntime。
"""

from __future__ import annotations

import time
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import Any

from core.models import Message, Role
from core.provider import LLMProvider
from memory.manager import MemoryManager
from tools.runner import ToolRunner

from agent.actions import (
    ActAction,
    AskAction,
    AwaitConfirmAction,
    FinishAction,
    control_tool_definitions,
)
from agent.agent_log import agent_trace, clip
from agent.assemble import assemble_messages, select_system
from agent.evidence import EvidenceJournal
from agent.events import (
    AgentEvent,
    ErrorEvent,
    FinalAnswerEvent,
    PhaseEvent,
    RunCompleteEvent,
    RunStatsEvent,
    StepEvent,
    ToolCallEvent,
    ToolResultEvent,
)
from agent.loop.decide import DecideResult, decide
from agent.loop.exec_act import ExecResult, exec_acts


@dataclass
class RunResult:
    """一轮 Agent run 的终态。"""

    content: str = ""
    status: str = "completed"  # completed | waiting_user | failed | incomplete
    think_rounds: int = 0
    tool_calls: int = 0
    tool_errors: int = 0
    elapsed_ms: int = 0
    ok: bool = True
    error: str = ""
    journal_run_id: str = ""
    evidence_ids: list[str] = field(default_factory=list)
    cites: list[str] = field(default_factory=list)
    # 旧宿主兼容字段（已无 A2UI；Step5 拆除宿主时可删）
    present_mode: str = "markdown"
    a2ui_messages: list[dict[str, Any]] = field(default_factory=list)
    answer_parts: list[dict[str, Any]] = field(default_factory=list)


def _merge_tools(business_tools: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return list(business_tools) + control_tool_definitions()


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


def _clip_obs(text: str, limit: int = 240) -> str:
    t = (text or "").strip()
    if len(t) <= limit:
        return t
    return t[: limit - 1] + "…"


async def run_stream(
    *,
    llm: LLMProvider,
    memory: MemoryManager,
    runner: ToolRunner,
    tools: list[dict[str, Any]],
    trigger: Message | list[Message],
    system_before: str,
    system_after: str,
    max_rounds: int = 8,
    trigger_source: str = "user",
    journal: EvidenceJournal | None = None,
) -> AsyncIterator[AgentEvent | RunResult]:
    """执行一整轮：落库 trigger → Decide/Exec/Journal → finish/ask/confirm/失败。"""
    started = time.monotonic()
    tool_calls_n = 0
    tool_errors_n = 0
    rounds = 0
    evidence = journal or EvidenceJournal()

    triggers = [trigger] if isinstance(trigger, Message) else list(trigger)
    if not triggers:
        err = "trigger 为空"
        yield ErrorEvent(error=err, recoverable=False)
        yield RunCompleteEvent(
            status="failed",
            ok=False,
            error=err,
            journal_run_id=evidence.run_id,
        )
        yield RunResult(
            ok=False,
            status="failed",
            error=err,
            elapsed_ms=0,
            journal_run_id=evidence.run_id,
        )
        return

    turn_messages: list[Message] = []
    for msg in triggers:
        await _remember(memory, msg, source=trigger_source)
        turn_messages.append(msg)

    yield PhaseEvent(phase="running", route="typed_react")
    agent_trace(
        "run start",
        triggers=len(triggers),
        max_rounds=max_rounds,
        journal_run_id=evidence.run_id,
    )

    llm_tools = _merge_tools(tools)
    parse_retries = 0

    def _elapsed() -> int:
        return max(0, int((time.monotonic() - started) * 1000))

    def _finish_result(
        *,
        content: str,
        status: str,
        ok: bool,
        error: str = "",
        cites: list[str] | None = None,
    ) -> RunResult:
        return RunResult(
            content=content,
            status=status,
            ok=ok,
            error=error,
            think_rounds=rounds,
            tool_calls=tool_calls_n,
            tool_errors=tool_errors_n,
            elapsed_ms=_elapsed(),
            journal_run_id=evidence.run_id,
            evidence_ids=evidence.ids(),
            cites=list(cites or []),
        )

    while rounds < max_rounds:
        rounds += 1
        system = select_system(
            system_before=system_before,
            system_after=system_after,
            turn_messages=turn_messages,
        )
        messages = await assemble_messages(
            memory,
            system_prompt=system,
            turn_messages=turn_messages,
            journal=evidence,
        )

        decision: DecideResult | None = None
        async for item in decide(llm, messages, tools=llm_tools):
            if isinstance(item, AgentEvent):
                yield item
            elif isinstance(item, DecideResult):
                decision = item

        if decision is None:
            err = "Decide 未返回结果"
            yield ErrorEvent(error=err, recoverable=False)
            result = _finish_result(content="", status="failed", ok=False, error=err)
            yield RunCompleteEvent(
                status=result.status,
                content=result.content,
                ok=result.ok,
                error=result.error,
                journal_run_id=result.journal_run_id,
                evidence_ids=result.evidence_ids,
            )
            yield result
            return

        if decision.stream_error:
            result = _finish_result(
                content="",
                status="failed",
                ok=False,
                error=decision.stream_error,
            )
            yield RunCompleteEvent(
                status=result.status,
                content=result.content,
                ok=result.ok,
                error=result.error,
                journal_run_id=result.journal_run_id,
                evidence_ids=result.evidence_ids,
            )
            yield result
            return

        if decision.parse_error:
            parse_retries += 1
            evidence.append(
                step=rounds,
                kind="parse_reject",
                summary=decision.parse_error,
            )
            hint = Message(
                role=Role.USER,
                content=(
                    f"上一轮动作不合法：{decision.parse_error}。"
                    "请只选择：业务工具，或单独的 agent_ask / "
                    "agent_await_confirm / agent_finish 之一。"
                ),
            )
            turn_messages.append(hint)
            if parse_retries >= 2:
                err = f"动作解析失败：{decision.parse_error}"
                yield ErrorEvent(error=err, recoverable=False)
                result = _finish_result(
                    content="", status="failed", ok=False, error=err
                )
                yield RunCompleteEvent(
                    status=result.status,
                    content=result.content,
                    ok=result.ok,
                    error=result.error,
                    journal_run_id=result.journal_run_id,
                    evidence_ids=result.evidence_ids,
                )
                yield result
                return
            continue

        action = decision.action
        assert action is not None

        if isinstance(action, ActAction):
            exec_result: ExecResult | None = None
            step_ids: list[str] = []
            async for item in exec_acts(
                action.tool_calls,
                runner,
                assistant_content=action.content,
                reasoning_content=action.reasoning_content,
            ):
                if isinstance(item, AgentEvent):
                    if isinstance(item, ToolCallEvent):
                        tool_calls_n += 1
                    if isinstance(item, ToolResultEvent):
                        if item.is_error:
                            tool_errors_n += 1
                        entry = evidence.append(
                            step=rounds,
                            kind="observation",
                            summary=_clip_obs(item.result),
                            tool_name=item.tool_name,
                            call_id=item.call_id,
                            is_error=item.is_error,
                            detail=item.result,
                        )
                        step_ids.append(entry.id)
                        item.journal_id = entry.id
                    yield item
                elif isinstance(item, ExecResult):
                    exec_result = item

            yield StepEvent(step=rounds, action="act", journal_ids=list(step_ids))

            if exec_result is None or not exec_result.messages:
                err = "Exec 未返回消息"
                yield ErrorEvent(error=err, recoverable=False)
                result = _finish_result(
                    content="", status="failed", ok=False, error=err
                )
                yield RunCompleteEvent(
                    status=result.status,
                    content=result.content,
                    ok=result.ok,
                    error=result.error,
                    journal_run_id=result.journal_run_id,
                    evidence_ids=result.evidence_ids,
                )
                yield result
                return

            for m in exec_result.messages:
                await _remember(memory, m, source="agent")
                turn_messages.append(m)
            parse_retries = 0
            continue

        # Ask / Confirm / Finish → 结束本 Run（Wait Profile 后续 Step）
        if isinstance(action, AskAction):
            content = action.question
            entry = evidence.append(
                step=rounds, kind="ask", summary=_clip_obs(content)
            )
            yield StepEvent(
                step=rounds, action="ask", journal_ids=[entry.id]
            )
            await _remember(
                memory,
                Message(role=Role.ASSISTANT, content=content),
                source="agent",
                metadata={"status": "waiting_user", "kind": "ask"},
            )
            result = _finish_result(
                content=content, status="waiting_user", ok=True
            )
            yield FinalAnswerEvent(content=content)
            yield RunStatsEvent(
                steps=rounds,
                tool_calls=tool_calls_n,
                tool_errors=tool_errors_n,
                elapsed_ms=result.elapsed_ms,
            )
            yield RunCompleteEvent(
                status=result.status,
                content=result.content,
                ok=result.ok,
                journal_run_id=result.journal_run_id,
                evidence_ids=result.evidence_ids,
            )
            yield result
            return

        if isinstance(action, AwaitConfirmAction):
            content = action.prompt
            entry = evidence.append(
                step=rounds,
                kind="await_confirm",
                summary=_clip_obs(content),
            )
            yield StepEvent(
                step=rounds,
                action="await_confirm",
                journal_ids=[entry.id],
            )
            await _remember(
                memory,
                Message(role=Role.ASSISTANT, content=content),
                source="agent",
                metadata={"status": "waiting_user", "kind": "await_confirm"},
            )
            result = _finish_result(
                content=content, status="waiting_user", ok=True
            )
            yield FinalAnswerEvent(content=content)
            yield RunStatsEvent(
                steps=rounds,
                tool_calls=tool_calls_n,
                tool_errors=tool_errors_n,
                elapsed_ms=result.elapsed_ms,
            )
            yield RunCompleteEvent(
                status=result.status,
                content=result.content,
                ok=result.ok,
                journal_run_id=result.journal_run_id,
                evidence_ids=result.evidence_ids,
            )
            yield result
            return

        if isinstance(action, FinishAction):
            content = action.summary
            entry = evidence.append(
                step=rounds,
                kind="finish",
                summary=_clip_obs(content),
            )
            yield StepEvent(
                step=rounds, action="finish", journal_ids=[entry.id]
            )
            await _remember(
                memory,
                Message(role=Role.ASSISTANT, content=content),
                source="agent",
                metadata={"status": "completed", "cites": action.cites},
            )
            agent_trace(
                "run finish",
                preview=clip(content, 120),
                rounds=rounds,
                journal_run_id=evidence.run_id,
                evidence_n=len(evidence.entries),
            )
            result = _finish_result(
                content=content,
                status="completed",
                ok=True,
                cites=action.cites,
            )
            yield FinalAnswerEvent(content=content)
            yield RunStatsEvent(
                steps=rounds,
                tool_calls=tool_calls_n,
                tool_errors=tool_errors_n,
                elapsed_ms=result.elapsed_ms,
            )
            yield RunCompleteEvent(
                status=result.status,
                content=result.content,
                ok=result.ok,
                journal_run_id=result.journal_run_id,
                evidence_ids=result.evidence_ids,
            )
            yield result
            return

    # 触顶
    summary = "已达最大推理轮次，本轮未完成。请换个说法再试或补充信息。"
    yield ErrorEvent(error=summary, recoverable=True)
    result = _finish_result(
        content=summary, status="incomplete", ok=False, error=summary
    )
    yield RunCompleteEvent(
        status=result.status,
        content=result.content,
        ok=result.ok,
        error=result.error,
        journal_run_id=result.journal_run_id,
        evidence_ids=result.evidence_ids,
    )
    yield result


# 别名：文档 / 双轨称呼
run_stream_v2 = run_stream
