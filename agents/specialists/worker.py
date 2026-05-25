"""基于 LLM + 角色提示词的专业 Agent 工人。"""

from __future__ import annotations

import json
import time
from collections.abc import AsyncIterator
from typing import Any

from core.models import Message, Role
from core.provider import (
    DeltaEvent,
    LLMProvider,
    StreamEndEvent,
    StreamErrorEvent,
)

from agents.events import StepOutputDeltaEvent
from agents.plan_models import SubTaskResult

PROGRAMMING_SYSTEM = """你是灵枢的专业 Agent · **编程与技术规格**。

职责：根据任务描述与上游意图，输出软件开发相关的技术规格片段（非法律条文）。
要求：
- 紧扣任务与 slots 中的预算、交付要求
- 结构清晰：范围、交付物、里程碑、验收要点
- 篇幅适中（约 300～800 字），不要写完整合同
- 使用中文，条目化表述"""

LEGAL_SYSTEM = """你是灵枢的专业 Agent · **法律条款**。

职责：根据任务描述、用户意图与前置技术规格，输出合同法律条款片段。
要求：
- 必须覆盖任务中提到的必备条款（如源代码归属、付款节点等）
- 若 context 中有 dependency_outputs，将其作为技术附件要点融入条款
- 结构：定义、权利义务、付款、知识产权、违约责任等（可按需取舍）
- 篇幅适中（约 400～1000 字），条款编号清晰
- 使用中文；可注明「草案，需法务审核」"""


def _build_user_prompt(
    *,
    task_description: str,
    expected_output: str,
    context: dict[str, Any],
) -> str:
    parts = [
        "## 本步任务",
        task_description,
        "",
        "## 预期产出",
        expected_output or "（见任务描述）",
        "",
        "## 用户意图（StructuredIntent）",
        json.dumps(context.get("intent") or {}, ensure_ascii=False, indent=2),
    ]
    deps = context.get("dependency_outputs") or {}
    if deps:
        parts.extend(["", "## 前置步骤产出（须参考）"])
        for step_id, text in sorted(deps.items(), key=lambda x: int(x[0])):
            parts.append(f"### 步骤 {step_id}\n{text}")
    if context.get("is_revision") and context.get("revision_feedback"):
        parts.extend(
            [
                "",
                "## 审查打回 · 须按下列意见修订本步产出",
                str(context.get("revision_feedback")),
            ]
        )
    return "\n".join(parts)


class LLMSpecialistAgent:
    """单角色专业 Agent：一次 LLM 调用完成子任务。"""

    def __init__(
        self,
        llm: LLMProvider,
        *,
        agent_id: str,
        agent_type: str,
        system_prompt: str,
    ) -> None:
        self.llm = llm
        self.agent_id = agent_id
        self.agent_type = agent_type
        self.system_prompt = system_prompt.strip()

    def _messages(
        self,
        *,
        task_description: str,
        expected_output: str,
        context: dict[str, Any],
    ) -> list[Message]:
        user_content = _build_user_prompt(
            task_description=task_description,
            expected_output=expected_output,
            context=context,
        )
        return [
            Message(role=Role.SYSTEM, content=self.system_prompt),
            Message(role=Role.USER, content=user_content),
        ]

    async def run(
        self,
        *,
        task_description: str,
        expected_output: str,
        context: dict[str, Any],
    ) -> SubTaskResult:
        start = time.monotonic()
        try:
            out = await self.llm.generate(
                messages=self._messages(
                    task_description=task_description,
                    expected_output=expected_output,
                    context=context,
                ),
                tools=None,
            )
            content = (out.content or "").strip()
            if not content:
                return SubTaskResult(
                    success=False,
                    content="",
                    error="专业 Agent 返回空内容",
                    agent_id=self.agent_id,
                    elapsed_ms=int((time.monotonic() - start) * 1000),
                )
            return SubTaskResult(
                success=True,
                content=content,
                agent_id=self.agent_id,
                elapsed_ms=int((time.monotonic() - start) * 1000),
            )
        except Exception as exc:
            return SubTaskResult(
                success=False,
                content="",
                error=str(exc),
                agent_id=self.agent_id,
                elapsed_ms=int((time.monotonic() - start) * 1000),
            )

    async def run_stream(
        self,
        *,
        step_id: int,
        task_description: str,
        expected_output: str,
        context: dict[str, Any],
    ) -> AsyncIterator[StepOutputDeltaEvent | SubTaskResult]:
        start = time.monotonic()
        messages = self._messages(
            task_description=task_description,
            expected_output=expected_output,
            context=context,
        )
        content_parts: list[str] = []
        try:
            async for ev in self.llm.generate_stream(messages=messages, tools=None):
                if isinstance(ev, DeltaEvent):
                    content_parts.append(ev.delta)
                    yield StepOutputDeltaEvent(step_id=step_id, delta=ev.delta)
                elif isinstance(ev, StreamEndEvent):
                    if ev.output.content:
                        content_parts = [ev.output.content]
                elif isinstance(ev, StreamErrorEvent):
                    yield SubTaskResult(
                        success=False,
                        content="",
                        error=str(ev.error),
                        agent_id=self.agent_id,
                        elapsed_ms=int((time.monotonic() - start) * 1000),
                    )
                    return
        except Exception as exc:
            yield SubTaskResult(
                success=False,
                content="",
                error=str(exc),
                agent_id=self.agent_id,
                elapsed_ms=int((time.monotonic() - start) * 1000),
            )
            return

        content = "".join(content_parts).strip()
        if not content:
            yield SubTaskResult(
                success=False,
                content="",
                error="专业 Agent 返回空内容",
                agent_id=self.agent_id,
                elapsed_ms=int((time.monotonic() - start) * 1000),
            )
            return
        yield SubTaskResult(
            success=True,
            content=content,
            agent_id=self.agent_id,
            elapsed_ms=int((time.monotonic() - start) * 1000),
        )


def create_default_specialists(llm: LLMProvider) -> dict[str, LLMSpecialistAgent]:
    """与 test / 默认 Registry 对齐的 programming、legal 工人。"""
    return {
        "programming": LLMSpecialistAgent(
            llm,
            agent_id="prog-001",
            agent_type="programming",
            system_prompt=PROGRAMMING_SYSTEM,
        ),
        "legal": LLMSpecialistAgent(
            llm,
            agent_id="legal-001",
            agent_type="legal",
            system_prompt=LEGAL_SYSTEM,
        ),
    }
