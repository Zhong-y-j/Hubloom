"""PlanExecute Execute 阶段：按 Registry 分发到 LLM 专业 Agent。"""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any

from core.provider import LLMProvider

from agents.events import StepOutputDeltaEvent
from agents.plan_models import ExecutionStep, SubTaskResult
from agents.specialists.worker import LLMSpecialistAgent, create_default_specialists


class RegistryStepDelegate:
    """将 plan 中的每一步分发给已注册的专业 Agent（LLM + 角色提示词）。"""

    def __init__(
        self,
        llm: LLMProvider,
        *,
        specialists: dict[str, LLMSpecialistAgent] | None = None,
    ) -> None:
        self._by_type = specialists or create_default_specialists(llm)
        self._by_id = {w.agent_id: w for w in self._by_type.values()}

    def register(self, worker: LLMSpecialistAgent) -> None:
        self._by_type[worker.agent_type] = worker
        self._by_id[worker.agent_id] = worker

    def _resolve_worker(
        self, step: ExecutionStep, agent_info: dict[str, Any]
    ) -> LLMSpecialistAgent | None:
        agent_id = str(agent_info.get("agent_id") or "")
        if agent_id and agent_id in self._by_id:
            return self._by_id[agent_id]
        return self._by_type.get(step.agent_type)

    async def delegate(
        self,
        *,
        step: ExecutionStep,
        agent_info: dict[str, Any],
        context: dict[str, Any],
    ) -> SubTaskResult:
        worker = self._resolve_worker(step, agent_info)
        if worker is None:
            return SubTaskResult(
                success=False,
                content="",
                error=f"未注册的专业 Agent: {step.agent_type!r}",
                agent_id=str(agent_info.get("agent_id") or ""),
            )
        return await worker.run(
            task_description=step.task_description,
            expected_output=step.expected_output,
            context=context,
        )

    async def delegate_stream(
        self,
        *,
        step: ExecutionStep,
        agent_info: dict[str, Any],
        context: dict[str, Any],
    ) -> AsyncIterator[StepOutputDeltaEvent | SubTaskResult]:
        worker = self._resolve_worker(step, agent_info)
        if worker is None:
            yield SubTaskResult(
                success=False,
                content="",
                error=f"未注册的专业 Agent: {step.agent_type!r}",
                agent_id=str(agent_info.get("agent_id") or ""),
            )
            return
        async for item in worker.run_stream(
            step_id=step.step_id,
            task_description=step.task_description,
            expected_output=step.expected_output,
            context=context,
        ):
            yield item
