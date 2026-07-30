"""Orchestrator：Policy-Bounded Typed ReAct（Step 3：Wait Profile）。

Decide → Act|Ask|AwaitConfirm|Finish；Journal；按 wait_profile 等人。
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
    AwaitingUserEvent,
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
from agent.session import (
    AwaitingSnapshot,
    PendingState,
    SessionStore,
    WaitKind,
    cancel_awaiting,
    ensure_record,
    new_await_token,
)
from agent.wait import WaitProfile, normalize_wait_profile


@dataclass
class RunResult:
    """一轮 Agent run 的终态或 interactive 挂起点。"""

    content: str = ""
    status: str = "completed"
    # completed | waiting_user | awaiting_user | failed | incomplete
    think_rounds: int = 0
    tool_calls: int = 0
    tool_errors: int = 0
    elapsed_ms: int = 0
    ok: bool = True
    error: str = ""
    journal_run_id: str = ""
    evidence_ids: list[str] = field(default_factory=list)
    cites: list[str] = field(default_factory=list)
    wait_profile: str = "turn_based"
    pending: PendingState | None = None
    await_token: str = ""
    # 旧宿主兼容（Step5 可删）
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


def _emit_terminal(
    result: RunResult,
) -> list[AgentEvent | RunResult]:
    out: list[AgentEvent | RunResult] = [
        RunStatsEvent(
            steps=result.think_rounds,
            tool_calls=result.tool_calls,
            tool_errors=result.tool_errors,
            elapsed_ms=result.elapsed_ms,
        ),
        RunCompleteEvent(
            status=result.status,
            content=result.content,
            ok=result.ok,
            error=result.error,
            journal_run_id=result.journal_run_id,
            evidence_ids=result.evidence_ids,
        ),
        result,
    ]
    return out


async def _agent_loop(
    *,
    llm: LLMProvider,
    memory: MemoryManager,
    runner: ToolRunner,
    tools: list[dict[str, Any]],
    system_before: str,
    system_after: str,
    max_rounds: int,
    wait_profile: WaitProfile,
    evidence: EvidenceJournal,
    turn_messages: list[Message],
    rounds: int,
    tool_calls_n: int,
    tool_errors_n: int,
    started: float,
    parse_retries: int,
    pending: PendingState | None,
    session_id: str | None,
    store: SessionStore | None,
) -> AsyncIterator[AgentEvent | RunResult]:
    llm_tools = _merge_tools(tools)
    active_pending = pending

    def _elapsed() -> int:
        return max(0, int((time.monotonic() - started) * 1000))

    def _finish_result(
        *,
        content: str,
        status: str,
        ok: bool,
        error: str = "",
        cites: list[str] | None = None,
        pending_out: PendingState | None = None,
        await_token: str = "",
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
            wait_profile=wait_profile,
            pending=pending_out,
            await_token=await_token,
        )

    async def _handle_wait(
        *,
        kind: WaitKind,
        prompt: str,
        slots: list[str],
        payload: dict[str, Any],
    ) -> AsyncIterator[AgentEvent | RunResult]:
        nonlocal active_pending

        entry = evidence.append(
            step=rounds,
            kind=kind,
            summary=_clip_obs(prompt),
        )
        yield StepEvent(step=rounds, action=kind, journal_ids=[entry.id])

        if wait_profile == "no_wait":
            summary = (
                f"当前入口不允许等待用户（no_wait），无法完成追问/确认："
                f"{prompt}"
            )
            await _remember(
                memory,
                Message(role=Role.ASSISTANT, content=summary),
                source="agent",
                metadata={"status": "failed", "kind": kind, "wait_profile": "no_wait"},
            )
            result = _finish_result(
                content=summary, status="failed", ok=False, error=summary
            )
            if store and session_id:
                rec = ensure_record(store, session_id)
                rec.status = "idle"
                rec.awaiting = None
                rec.active_run_id = None
                store.put(rec)
            yield FinalAnswerEvent(content=summary)
            for item in _emit_terminal(result):
                yield item
            return

        await _remember(
            memory,
            Message(role=Role.ASSISTANT, content=prompt),
            source="agent",
            metadata={
                "status": "waiting_user"
                if wait_profile == "turn_based"
                else "awaiting_user",
                "kind": kind,
                "wait_profile": wait_profile,
            },
        )
        yield FinalAnswerEvent(content=prompt)

        if wait_profile == "turn_based":
            pending_out = PendingState(
                kind=kind,
                prompt=prompt,
                slots=list(slots),
                payload=dict(payload),
                intent=prompt,
                from_run_id=evidence.run_id,
                evidence_ids=evidence.ids(),
            )
            active_pending = pending_out
            if store and session_id:
                rec = ensure_record(store, session_id)
                rec.status = "idle"
                rec.pending = pending_out
                rec.awaiting = None
                rec.active_run_id = None
                store.put(rec)
            result = _finish_result(
                content=prompt,
                status="waiting_user",
                ok=True,
                pending_out=pending_out,
            )
            for item in _emit_terminal(result):
                yield item
            return

        # interactive：挂起同一 Run
        token = new_await_token()
        snap = AwaitingSnapshot(
            run_id=evidence.run_id,
            await_token=token,
            kind=kind,
            prompt=prompt,
            slots=list(slots),
            payload=dict(payload),
            journal=evidence,
            turn_messages=list(turn_messages),
            rounds=rounds,
            tool_calls_n=tool_calls_n,
            tool_errors_n=tool_errors_n,
            started=started,
            system_before=system_before,
            system_after=system_after,
            parse_retries=parse_retries,
            max_rounds=max_rounds,
        )
        if store is None or not session_id:
            err = "interactive 挂起需要 session_id + SessionStore"
            yield ErrorEvent(error=err, recoverable=False)
            result = _finish_result(content="", status="failed", ok=False, error=err)
            for item in _emit_terminal(result):
                yield item
            return

        rec = ensure_record(store, session_id)
        rec.status = "awaiting_user"
        rec.awaiting = snap
        rec.active_run_id = evidence.run_id
        rec.pending = None
        store.put(rec)

        yield AwaitingUserEvent(
            run_id=evidence.run_id,
            await_token=token,
            kind=kind,
            prompt=prompt,
            slots=list(slots),
            payload=dict(payload),
        )
        result = _finish_result(
            content=prompt,
            status="awaiting_user",
            ok=True,
            await_token=token,
        )
        # 挂起不是终态：不发 RunCompleteEvent
        yield RunStatsEvent(
            steps=result.think_rounds,
            tool_calls=result.tool_calls,
            tool_errors=result.tool_errors,
            elapsed_ms=result.elapsed_ms,
        )
        yield result

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
            pending=active_pending,
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
            for item in _emit_terminal(result):
                yield item
            return

        if decision.stream_error:
            result = _finish_result(
                content="",
                status="failed",
                ok=False,
                error=decision.stream_error,
            )
            for item in _emit_terminal(result):
                yield item
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
                for item in _emit_terminal(result):
                    yield item
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
                for item in _emit_terminal(result):
                    yield item
                return

            for m in exec_result.messages:
                await _remember(memory, m, source="agent")
                turn_messages.append(m)
            parse_retries = 0
            continue

        if isinstance(action, AskAction):
            async for item in _handle_wait(
                kind="ask",
                prompt=action.question,
                slots=list(action.slots),
                payload={},
            ):
                yield item
            return

        if isinstance(action, AwaitConfirmAction):
            async for item in _handle_wait(
                kind="await_confirm",
                prompt=action.prompt,
                slots=[],
                payload=dict(action.payload),
            ):
                yield item
            return

        if isinstance(action, FinishAction):
            content = action.summary
            entry = evidence.append(
                step=rounds,
                kind="finish",
                summary=_clip_obs(content),
            )
            yield StepEvent(step=rounds, action="finish", journal_ids=[entry.id])
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
            if store and session_id:
                rec = ensure_record(store, session_id)
                rec.status = "idle"
                rec.pending = None
                rec.awaiting = None
                rec.active_run_id = None
                store.put(rec)
            result = _finish_result(
                content=content,
                status="completed",
                ok=True,
                cites=action.cites,
            )
            yield FinalAnswerEvent(content=content)
            for item in _emit_terminal(result):
                yield item
            return

    summary = "已达最大推理轮次，本轮未完成。请换个说法再试或补充信息。"
    yield ErrorEvent(error=summary, recoverable=True)
    result = _finish_result(
        content=summary, status="incomplete", ok=False, error=summary
    )
    for item in _emit_terminal(result):
        yield item


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
    wait_profile: str | WaitProfile = "turn_based",
    pending: PendingState | None = None,
    session_id: str | None = None,
    store: SessionStore | None = None,
) -> AsyncIterator[AgentEvent | RunResult]:
    """新开一轮 Run。interactive 挂起中禁止再 begin（须 resume/cancel）。"""
    profile = normalize_wait_profile(str(wait_profile))
    evidence = journal or EvidenceJournal()
    started = time.monotonic()

    if store and session_id:
        rec = store.get(session_id)
        if rec is not None and rec.status == "awaiting_user":
            err = (
                "session 正在 awaiting_user，请先 resume 或 cancel，"
                "禁止并行 begin_run"
            )
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
                journal_run_id=evidence.run_id,
                wait_profile=profile,
            )
            return
        rec = ensure_record(store, session_id)
        # turn_based：若调用方未显式传 pending，沿用 store 里的
        if pending is None and profile == "turn_based" and rec.pending is not None:
            pending = rec.pending
        rec.status = "running"
        rec.active_run_id = evidence.run_id
        rec.awaiting = None
        store.put(rec)

    triggers = [trigger] if isinstance(trigger, Message) else list(trigger)
    if not triggers:
        err = "trigger 为空"
        yield ErrorEvent(error=err, recoverable=False)
        result = RunResult(
            ok=False,
            status="failed",
            error=err,
            journal_run_id=evidence.run_id,
            wait_profile=profile,
        )
        yield RunCompleteEvent(
            status="failed",
            ok=False,
            error=err,
            journal_run_id=evidence.run_id,
        )
        yield result
        return

    turn_messages: list[Message] = []
    for msg in triggers:
        await _remember(memory, msg, source=trigger_source)
        turn_messages.append(msg)

    yield PhaseEvent(phase="running", route=f"typed_react:{profile}")
    agent_trace(
        "run start",
        triggers=len(triggers),
        max_rounds=max_rounds,
        journal_run_id=evidence.run_id,
        wait_profile=profile,
        pending=bool(pending),
    )

    async for item in _agent_loop(
        llm=llm,
        memory=memory,
        runner=runner,
        tools=tools,
        system_before=system_before,
        system_after=system_after,
        max_rounds=max_rounds,
        wait_profile=profile,
        evidence=evidence,
        turn_messages=turn_messages,
        rounds=0,
        tool_calls_n=0,
        tool_errors_n=0,
        started=started,
        parse_retries=0,
        pending=pending,
        session_id=session_id,
        store=store,
    ):
        yield item


async def resume_stream(
    *,
    llm: LLMProvider,
    memory: MemoryManager,
    runner: ToolRunner,
    tools: list[dict[str, Any]],
    session_id: str,
    store: SessionStore,
    user_reply: Message | str,
    run_id: str | None = None,
    await_token: str | None = None,
    trigger_source: str = "user",
) -> AsyncIterator[AgentEvent | RunResult]:
    """interactive：用用户回复恢复同一 Run。"""
    rec = store.get(session_id)
    if rec is None or rec.awaiting is None:
        err = "没有可 resume 的 awaiting 状态"
        yield ErrorEvent(error=err, recoverable=False)
        yield RunResult(ok=False, status="failed", error=err, wait_profile="interactive")
        return

    snap = rec.awaiting
    if run_id is not None and snap.run_id != run_id:
        err = f"run_id 不匹配：期望 {snap.run_id}"
        yield ErrorEvent(error=err, recoverable=False)
        yield RunResult(ok=False, status="failed", error=err, wait_profile="interactive")
        return
    if await_token is not None and snap.await_token != await_token:
        err = "await_token 无效或已过期"
        yield ErrorEvent(error=err, recoverable=False)
        yield RunResult(ok=False, status="failed", error=err, wait_profile="interactive")
        return

    reply = (
        user_reply
        if isinstance(user_reply, Message)
        else Message(role=Role.USER, content=str(user_reply))
    )
    await _remember(memory, reply, source=trigger_source)
    turn_messages = list(snap.turn_messages)
    turn_messages.append(reply)

    # 用户回复记作观察，便于 Journal / cites
    snap.journal.append(
        step=snap.rounds,
        kind="observation",
        summary=_clip_obs(reply.content or ""),
        tool_name="user_reply",
        detail=reply.content or "",
    )

    rec.status = "running"
    rec.awaiting = None
    store.put(rec)

    yield PhaseEvent(phase="running", route="typed_react:interactive:resume")
    agent_trace(
        "run resume",
        journal_run_id=snap.run_id,
        await_kind=snap.kind,
    )

    async for item in _agent_loop(
        llm=llm,
        memory=memory,
        runner=runner,
        tools=tools,
        system_before=snap.system_before,
        system_after=snap.system_after,
        max_rounds=snap.max_rounds,
        wait_profile="interactive",
        evidence=snap.journal,
        turn_messages=turn_messages,
        rounds=snap.rounds,
        tool_calls_n=snap.tool_calls_n,
        tool_errors_n=snap.tool_errors_n,
        started=snap.started,
        parse_retries=snap.parse_retries,
        pending=None,
        session_id=session_id,
        store=store,
    ):
        yield item


# 别名
run_stream_v2 = run_stream

__all__ = [
    "RunResult",
    "run_stream",
    "run_stream_v2",
    "resume_stream",
    "cancel_awaiting",
]
