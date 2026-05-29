"""灵枢 Hub：串联 ReAct → PlanExecute → Reflection →（可选）修订重跑。"""

from __future__ import annotations

import time
import uuid
from collections.abc import AsyncIterator

from agents.core.agent_log import clear_turn_id, hub_log, set_turn_id
from agents.core.events import (
    AgentEvent,
    ErrorEvent,
    ExecutionResultEvent,
    HubPhaseEvent,
    HubTurnCompleteEvent,
    PlanReadyEvent,
)
from agents.hub.models import (
    ROUTE_CLARIFY_ONLY,
    ROUTE_DIRECT_REPLY,
    ROUTE_PLAN_EXECUTE,
    ROUTE_PLAN_REFLECT,
    ROUTE_PLAN_REVISE,
    ROUTE_PLAN_REVISE_REFLECT,
    HubTurnOutcome,
)
from agents.core.intent import StructuredIntent
from agents.plan.execute import LLMPlanGenerator, PlanExecuteAgent, expand_rerun_step_ids
from agents.plan.models import ExecutionResult, StepStatus
from agents.react.agent import ReActAgent
from agents.reflection.agent import ReflectionAgent
from agents.reflection.models import ReflectionVerdict


class CortexHub:
    """编排 ReAct、PlanExecute、Reflection 的中枢。

    单轮 ``run_turn_stream(user_message)``：
    1. ReAct 澄清 / 结构化意图
    2. 若 ``should_invoke_plan()`` → Plan（可先流式 Plan）→ Execute
    3. 若启用 Reflection → 审查 ExecutionResult
    4. 若审查不通过且 ``max_revision_rounds > 0`` → 按 ``related_step_ids`` 修订重跑
    5. ``HubTurnCompleteEvent`` 汇总 ``user_reply`` + ``deliverable``
    """

    def __init__(
        self,
        react: ReActAgent,
        plan_execute: PlanExecuteAgent,
        reflection: ReflectionAgent | None = None,
        *,
        run_reflection: bool = True,
        stream_plan_separately: bool = True,
        max_revision_rounds: int = 1,
    ) -> None:
        self.react = react
        self.plan_execute = plan_execute
        self.reflection = reflection
        self.run_reflection = run_reflection and reflection is not None
        self.stream_plan_separately = stream_plan_separately
        self.max_revision_rounds = max(0, max_revision_rounds)
        self.last_outcome: HubTurnOutcome | None = None

    async def run_turn_stream(
        self, user_message: str
    ) -> AsyncIterator[AgentEvent]:
        """处理用户一条输入，透传各阶段事件，末尾产出 HubTurnCompleteEvent。"""
        message = (user_message or "").strip()
        turn_id = uuid.uuid4().hex[:8]
        set_turn_id(turn_id)
        turn_start = time.monotonic()

        hub_log(
            "turn start",
            message_len=len(message),
            run_reflection=self.run_reflection,
            max_revision_rounds=self.max_revision_rounds,
        )

        try:
            if not message:
                hub_log("turn abort", reason="empty_message")
                yield ErrorEvent(error="user_message 不能为空")
                return

            yield HubPhaseEvent(phase="react")
            async for ev in self.react.run_stream(message):
                yield ev

            intent = self.react.get_last_intent()
            if intent is None:
                hub_log("route", route=ROUTE_CLARIFY_ONLY, reason="no_intent")
                outcome = HubTurnOutcome(
                    route=ROUTE_CLARIFY_ONLY,
                    user_reply="",
                )
                self.last_outcome = outcome
                yield HubTurnCompleteEvent(
                    route=outcome.route,
                    user_reply=outcome.user_reply,
                )
                return

            user_reply = (intent.user_reply or "").strip()
            hub_log(
                "react done",
                intent=intent.intent,
                is_clear=intent.is_clear,
                should_plan=intent.should_invoke_plan(),
            )

            if not intent.is_clear:
                hub_log("route", route=ROUTE_CLARIFY_ONLY)
                outcome = HubTurnOutcome(
                    route=ROUTE_CLARIFY_ONLY,
                    user_reply=user_reply,
                    intent=intent,
                )
                self.last_outcome = outcome
                yield HubTurnCompleteEvent(
                    route=outcome.route,
                    user_reply=outcome.user_reply,
                    intent=intent,
                )
                return

            if not intent.should_invoke_plan():
                hub_log("route", route=ROUTE_DIRECT_REPLY)
                outcome = HubTurnOutcome(
                    route=ROUTE_DIRECT_REPLY,
                    user_reply=user_reply,
                    intent=intent,
                )
                self.last_outcome = outcome
                yield HubTurnCompleteEvent(
                    route=outcome.route,
                    user_reply=outcome.user_reply,
                    intent=intent,
                )
                return

            yield HubPhaseEvent(phase="plan")
            result: ExecutionResult | None = None
            plan_start = time.monotonic()
            async for ev in self._run_plan_pipeline(intent):
                yield ev
                if isinstance(ev, ExecutionResultEvent):
                    result = ev.result
                if isinstance(ev, ErrorEvent):
                    hub_log(
                        "plan pipeline error",
                        error=ev.error,
                        plan_ms=int((time.monotonic() - plan_start) * 1000),
                    )
                    outcome = HubTurnOutcome(
                        route=ROUTE_PLAN_EXECUTE,
                        user_reply=user_reply,
                        intent=intent,
                        execution_result=ExecutionResult(
                            deliverable=f"执行失败：{ev.error}",
                            source_intent=intent,
                        ),
                    )
                    self.last_outcome = outcome
                    yield HubTurnCompleteEvent(
                        route=outcome.route,
                        user_reply=outcome.user_reply,
                        deliverable=outcome.execution_result.deliverable
                        if outcome.execution_result
                        else None,
                        intent=intent,
                        execution_result=outcome.execution_result,
                    )
                    return

            if result is None:
                result = self.plan_execute.get_last_result()

            hub_log(
                "plan pipeline done",
                plan_ms=int((time.monotonic() - plan_start) * 1000),
                deliverable_len=len((result.deliverable or "") if result else ""),
                trace_steps=len(result.trace) if result else 0,
            )

            verdict: ReflectionVerdict | None = None
            route = ROUTE_PLAN_EXECUTE
            revision_rounds = 0

            if self.run_reflection and self.reflection is not None and result is not None:
                yield HubPhaseEvent(phase="reflection")
                async for ev in self._reflection_events(result):
                    yield ev
                verdict = self.reflection.get_last_verdict()
                route = ROUTE_PLAN_REFLECT
                hub_log(
                    "reflection done",
                    passed=verdict.passed if verdict else None,
                    issues=len(verdict.issues) if verdict else 0,
                )

                if (
                    verdict is not None
                    and not verdict.passed
                    and self.max_revision_rounds > 0
                    and result.plan is not None
                ):
                    for _ in range(self.max_revision_rounds):
                        revision_rounds += 1
                        step_ids = _collect_rerun_step_ids(verdict, result)
                        rerun_set = expand_rerun_step_ids(result.plan, step_ids)
                        hub_log(
                            "revision start",
                            round=revision_rounds,
                            rerun_step_ids=sorted(rerun_set),
                        )
                        yield HubPhaseEvent(phase="revision")
                        revised: ExecutionResult | None = None
                        rev_start = time.monotonic()
                        async for ev in self._run_revision_pipeline(
                            intent, result, verdict
                        ):
                            yield ev
                            if isinstance(ev, ExecutionResultEvent):
                                revised = ev.result
                            if isinstance(ev, ErrorEvent):
                                hub_log(
                                    "revision error",
                                    round=revision_rounds,
                                    error=ev.error,
                                )
                                break
                        if revised is None:
                            revised = self.plan_execute.get_last_result()
                        if revised is not None:
                            result = revised
                        hub_log(
                            "revision done",
                            round=revision_rounds,
                            elapsed_ms=int((time.monotonic() - rev_start) * 1000),
                            deliverable_len=len((result.deliverable or "") if result else ""),
                        )

                        yield HubPhaseEvent(phase="reflection")
                        async for ev in self._reflection_events(result):
                            yield ev
                        verdict = self.reflection.get_last_verdict()
                        route = ROUTE_PLAN_REVISE_REFLECT
                        hub_log(
                            "reflection after revision",
                            round=revision_rounds,
                            passed=verdict.passed if verdict else None,
                        )
                        if verdict is not None and verdict.passed:
                            break

            if revision_rounds > 0 and route == ROUTE_PLAN_REFLECT:
                route = ROUTE_PLAN_REVISE

            deliverable = (result.deliverable or "").strip() if result else None
            outcome = HubTurnOutcome(
                route=route,
                user_reply=user_reply,
                deliverable=deliverable or None,
                intent=intent,
                execution_result=result,
                reflection_verdict=verdict,
                revision_rounds=revision_rounds,
            )
            self.last_outcome = outcome
            hub_log(
                "turn complete",
                route=route,
                revision_rounds=revision_rounds,
                deliverable_len=len(deliverable or ""),
                elapsed_ms=int((time.monotonic() - turn_start) * 1000),
            )
            yield HubTurnCompleteEvent(
                route=outcome.route,
                user_reply=outcome.user_reply,
                deliverable=outcome.deliverable,
                intent=intent,
                execution_result=result,
                reflection_verdict=verdict,
            )
        finally:
            clear_turn_id()

    async def _reflection_events(
        self, result: ExecutionResult
    ) -> AsyncIterator[AgentEvent]:
        if self.reflection is None:
            return
        async for ev in self.reflection.review_stream(result):
            if isinstance(ev, ErrorEvent):
                hub_log("reflection error", error=ev.error)
                yield ErrorEvent(error=f"Reflection 失败: {ev.error}")
                return
            yield ev

    async def _run_plan_pipeline(
        self, intent: StructuredIntent
    ) -> AsyncIterator[AgentEvent]:
        """Plan（可选流式）+ Execute。"""
        generator = self.plan_execute.plan_generator
        if self.stream_plan_separately and isinstance(generator, LLMPlanGenerator):
            plan = None
            t0 = time.monotonic()
            async for ev in generator.create_plan_stream(intent):
                yield ev
                if isinstance(ev, PlanReadyEvent):
                    plan = ev.plan
            if plan is None:
                hub_log("plan stream missing PlanReadyEvent")
                yield ErrorEvent(error="Plan 阶段未收到 PlanReadyEvent")
                return
            plan_ms = int((time.monotonic() - t0) * 1000)
            hub_log(
                "plan stream ready",
                steps=len(plan.steps),
                plan_ms=plan_ms,
            )
            async for ev in self.plan_execute.execute_stream(
                intent,
                plan=plan,
                skip_plan_generation=True,
            ):
                yield ev
            return

        async for ev in self.plan_execute.execute_stream(intent):
            yield ev

    async def _run_revision_pipeline(
        self,
        intent: StructuredIntent,
        prior: ExecutionResult,
        verdict: ReflectionVerdict,
    ) -> AsyncIterator[AgentEvent]:
        """按 Reflection 结论修订重跑部分步骤。"""
        plan = prior.plan
        if plan is None:
            yield ErrorEvent(error="修订重跑需要 ExecutionResult.plan")
            return

        step_ids = _collect_rerun_step_ids(verdict, prior)
        if not step_ids:
            yield ErrorEvent(error="无法确定需重跑的步骤")
            return

        rerun_set = expand_rerun_step_ids(plan, step_ids)
        prior_outputs = _prior_outputs_from_result(prior, rerun_set)
        feedback = _build_revision_feedback(verdict)

        async for ev in self.plan_execute.execute_stream(
            intent,
            plan=plan,
            skip_plan_generation=True,
            revision_feedback=feedback,
            rerun_step_ids=sorted(rerun_set),
            prior_outputs=prior_outputs,
        ):
            yield ev

    def get_last_outcome(self) -> HubTurnOutcome | None:
        return self.last_outcome


def _collect_rerun_step_ids(
    verdict: ReflectionVerdict, result: ExecutionResult
) -> list[int]:
    ids: set[int] = set()
    for issue in verdict.issues:
        if issue.severity == "error":
            ids.update(issue.related_step_ids)
    if not ids:
        for issue in verdict.issues:
            ids.update(issue.related_step_ids)
    if not ids and result.trace:
        for row in result.trace:
            if row.status == StepStatus.FAILED:
                ids.add(row.step_id)
    if not ids and result.plan and result.plan.steps:
        ids.add(max(s.step_id for s in result.plan.steps))
    return sorted(ids)


def _prior_outputs_from_result(
    result: ExecutionResult, rerun: set[int]
) -> dict[int, str]:
    outputs: dict[int, str] = {}
    for row in result.trace:
        if (
            row.step_id not in rerun
            and row.status == StepStatus.SUCCESS
            and row.output
        ):
            outputs[row.step_id] = row.output
    return outputs


def _build_revision_feedback(verdict: ReflectionVerdict) -> str:
    parts: list[str] = []
    if verdict.recommendation:
        parts.append(verdict.recommendation.strip())
    for i, issue in enumerate(verdict.issues, 1):
        if issue.severity == "error":
            sid = (
                f"（步骤 {issue.related_step_ids}）"
                if issue.related_step_ids
                else ""
            )
            parts.append(f"[问题 {i}]{sid} {issue.message}")
    return "\n".join(parts).strip()
