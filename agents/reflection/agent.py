"""Reflection Agent：对 PlanExecute 产出做 LLM 质量审查。"""

from __future__ import annotations

import json
import re
import time
from collections.abc import AsyncIterator
from typing import Any

from core.models import Message, Role
from core.provider import DeltaEvent, LLMProvider, StreamEndEvent, StreamErrorEvent

from agents.core.events import (
    AgentEvent,
    ErrorEvent,
    ReflectionCompleteEvent,
    ReflectionStartEvent,
    ReflectionTextDeltaEvent,
)
from agents.plan.models import ExecutionResult, ExecutionStepTrace, StepStatus
from agents.core.agent_log import clip, reflection_log
from agents.reflection.models import ReflectionIssue, ReflectionVerdict
from tools.transport_errors import extract_business_message, is_retryable_tool_error

_REFLECTION_JSON_BLOCK_RE = re.compile(
    r"```(?:json|reflection)?\s*\n(.*?)\n```",
    re.DOTALL | re.IGNORECASE,
)

REFLECTION_SYSTEM = """你是灵枢（Agent Cortex）**Reflection 质量审查员**。

## 职责
对照 PlanExecute 的原始结构化意图（StructuredIntent）、执行计划、分步轨迹与最终交付物（deliverable），做**只读**质量审查。

## 检查维度
1. **完整性**：StructuredIntent.summary / slots 中的关键诉求是否在 deliverable 中体现；若 slots 含 suggested_tools，对照执行轨迹是否调用了应调用的 MCP 工具。
2. **一致性**：各步骤产出（transport JSON / body）之间是否自相矛盾。
3. **意图符合**：deliverable 是否偏离 source_intent；勿用某一固定 API 或业务域的隐含规则评判，以本次 intent 与 plan 为准。
4. **可交付性**：是否明显占位、关键信息缺失或仅部分步骤成功（partial_success）。

## 禁止
- 不要重写完整交付物正文。
- 不要编造用户未提供的硬性事实。
- 不要要求调用当前 plan/轨迹中未出现、且 intent 未要求的特定工具名。
- 只输出审查意见与结构化结论。

## 输出格式
1. 简短中文审查说明（可先写若干条要点）。
2. 必须用 ```reflection 代码块包裹 JSON：

```reflection
{
  "passed": true,
  "summary": "一句总评",
  "issues": [
    {
      "severity": "error",
      "category": "intent_mismatch",
      "message": "具体问题描述",
      "related_step_ids": [2]
    }
  ],
  "recommendation": "给 Hub 的建议，如：补充缺失步骤或重跑 step 2"
}
```

规则：
- ``passed=true`` 且无 error 级 issues 时，表示建议通过审查。
- ``severity`` 仅 ``error`` 或 ``warning``。
- ``related_step_ids`` 填相关步骤编号，无则 ``[]``。
"""


def parse_reflection_json(text: str) -> dict[str, Any]:
    """从模型输出解析审查 JSON。"""
    raw = (text or "").strip()
    if not raw:
        return {}

    match = _REFLECTION_JSON_BLOCK_RE.search(raw)
    payload = match.group(1).strip() if match else raw
    try:
        data = json.loads(payload)
    except json.JSONDecodeError:
        start = raw.find("{")
        end = raw.rfind("}")
        if start < 0 or end <= start:
            return {}
        try:
            data = json.loads(raw[start : end + 1])
        except json.JSONDecodeError:
            return {}
    return data if isinstance(data, dict) else {}


def verdict_from_dict(data: dict[str, Any], *, review_report: str = "") -> ReflectionVerdict:
    """将解析后的 dict 转为 ReflectionVerdict。"""
    issues: list[ReflectionIssue] = []
    for raw in data.get("issues") or []:
        if not isinstance(raw, dict):
            continue
        deps = raw.get("related_step_ids") or []
        if not isinstance(deps, list):
            deps = []
        step_ids = [int(d) for d in deps if isinstance(d, (int, float))]
        issues.append(
            ReflectionIssue(
                severity=str(raw.get("severity") or "warning").strip().lower(),
                category=str(raw.get("category") or "general").strip(),
                message=str(raw.get("message") or "").strip(),
                related_step_ids=step_ids,
            )
        )

    passed = bool(data.get("passed", False))
    errors = [i for i in issues if i.severity == "error"]
    if errors:
        passed = False

    return ReflectionVerdict(
        passed=passed,
        summary=str(data.get("summary") or "").strip(),
        issues=issues,
        recommendation=str(data.get("recommendation") or "").strip(),
        review_report=review_report.strip(),
    )


def _rule_based_verdict(result: ExecutionResult) -> ReflectionVerdict | None:
    """L0：执行层失败时直接不通过，无需调用 LLM。"""
    issues: list[ReflectionIssue] = []
    for row in result.trace:
        if row.status == StepStatus.FAILED:
            issues.append(
                ReflectionIssue(
                    severity="error",
                    category="execution_failure",
                    message=row.error or f"步骤 {row.step_id} 执行失败",
                    related_step_ids=[row.step_id],
                )
            )
        elif row.status == StepStatus.SKIPPED:
            issues.append(
                ReflectionIssue(
                    severity="error",
                    category="execution_failure",
                    message=row.error or f"步骤 {row.step_id} 被跳过",
                    related_step_ids=[row.step_id],
                )
            )

    if not (result.deliverable or "").strip():
        issues.append(
            ReflectionIssue(
                severity="error",
                category="completeness",
                message="deliverable 为空",
                related_step_ids=[],
            )
        )

    if result.partial_success or issues:
        non_retryable = [
            row
            for row in result.trace
            if row.status == StepStatus.FAILED
            and not is_retryable_tool_error(row.error or "")
        ]
        if non_retryable:
            msgs = []
            for row in non_retryable:
                biz = extract_business_message(row.error or "")
                if biz:
                    msgs.append(biz)
            detail = "；".join(dict.fromkeys(msgs)) if msgs else ""
            rec = "失败步骤为 API 明确拒绝（业务规则/权限等），请向用户如实说明原因，勿重试相同工具调用。"
            summary = "执行部分成功，但存在不可通过重试修复的失败步骤。"
            if detail:
                summary = f"{summary} {detail}"
        else:
            rec = "建议 Hub 重跑失败/跳过的步骤，或整段 PlanExecute 后再审查。"
            summary = "执行未完全成功，未进入 LLM 深度审查。"
        return ReflectionVerdict(
            passed=False,
            summary=summary,
            issues=issues,
            recommendation=rec,
            review_report="",
        )
    return None


def _trace_excerpt(trace: list[ExecutionStepTrace], *, max_chars_per_step: int = 2500) -> str:
    parts: list[str] = []
    for row in sorted(trace, key=lambda t: t.step_id):
        body = (row.output or row.error or "（无产出）").strip()
        if len(body) > max_chars_per_step:
            body = body[:max_chars_per_step] + "\n…（截断）"
        parts.append(
            f"### 步骤 {row.step_id} · {row.agent_type} · {row.status.value}\n{body}"
        )
    return "\n\n".join(parts) if parts else "（无 trace）"


def _build_review_user_prompt(result: ExecutionResult) -> str:
    intent_block = (
        json.dumps(result.source_intent.to_dict(), ensure_ascii=False, indent=2)
        if result.source_intent
        else "（无 source_intent）"
    )
    plan_block = (
        json.dumps(result.plan.to_dict(), ensure_ascii=False, indent=2)
        if result.plan
        else "（无 plan）"
    )
    return (
        "## 原始结构化意图（StructuredIntent）\n"
        f"{intent_block}\n\n"
        "## 执行计划（ExecutionPlan）\n"
        f"{plan_block}\n\n"
        "## 分步轨迹（ExecutionStepTrace 摘要）\n"
        f"{_trace_excerpt(result.trace)}\n\n"
        "## 最终交付物（deliverable）\n"
        f"{(result.deliverable or '').strip() or '（空）'}\n\n"
        "请审查并输出 ```reflection``` JSON。"
    )


class ReflectionAgent:
    """对 PlanExecute 的 ExecutionResult 做 LLM 质量审查。

    输入：``ExecutionResult``（PlanExecute 输出）
    输出：``ReflectionVerdict``（结构化审查结论，供 Hub 决定是否交付或重跑 Plan）
    """

    def __init__(
        self,
        llm: LLMProvider,
        *,
        system_prompt: str | None = None,
    ) -> None:
        self.llm = llm
        self.system_prompt = (system_prompt or REFLECTION_SYSTEM).strip()
        self.last_verdict: ReflectionVerdict | None = None

    async def review(self, result: ExecutionResult) -> ReflectionVerdict:
        """非流式审查。"""
        final: ReflectionVerdict | None = None
        async for ev in self.review_stream(result):
            if isinstance(ev, ReflectionCompleteEvent):
                final = ev.verdict
            if isinstance(ev, ErrorEvent):
                return ReflectionVerdict(
                    passed=False,
                    summary=f"审查失败：{ev.error}",
                    issues=[
                        ReflectionIssue(
                            severity="error",
                            category="review_failure",
                            message=ev.error,
                        )
                    ],
                    recommendation="请检查 LLM 或输入后重试审查。",
                )
        return final or ReflectionVerdict(
            passed=False,
            summary="未产生 ReflectionVerdict",
            recommendation="请重试 review_stream。",
        )

    async def review_stream(
        self, result: ExecutionResult
    ) -> AsyncIterator[AgentEvent]:
        """流式审查：ReflectionTextDeltaEvent → ReflectionCompleteEvent(verdict)。"""
        start = time.monotonic()
        step_count = len(result.trace)
        reflection_log(
            "review_stream start",
            trace_steps=step_count,
            deliverable_len=len((result.deliverable or "")),
            partial_success=result.partial_success,
        )
        yield ReflectionStartEvent(
            step_count=step_count,
            partial_success=result.partial_success,
        )

        ruled = _rule_based_verdict(result)
        if ruled is not None:
            self.last_verdict = ruled
            elapsed_ms = int((time.monotonic() - start) * 1000)
            reflection_log(
                "review_stream rule_based",
                passed=ruled.passed,
                issues=len(ruled.issues),
                elapsed_ms=elapsed_ms,
            )
            yield ReflectionCompleteEvent(
                verdict=ruled,
                elapsed_ms=elapsed_ms,
            )
            return

        messages = [
            Message(role=Role.SYSTEM, content=self.system_prompt),
            Message(role=Role.USER, content=_build_review_user_prompt(result)),
        ]
        content_parts: list[str] = []
        try:
            async for ev in self.llm.generate_stream(messages=messages, tools=None):
                if isinstance(ev, DeltaEvent):
                    content_parts.append(ev.delta)
                    yield ReflectionTextDeltaEvent(delta=ev.delta)
                elif isinstance(ev, StreamEndEvent):
                    if ev.output.content:
                        content_parts = [ev.output.content]
                elif isinstance(ev, StreamErrorEvent):
                    reflection_log("review_stream llm error", error=str(ev.error))
                    yield ErrorEvent(error=str(ev.error))
                    return
        except Exception as exc:
            reflection_log("review_stream failed", error=str(exc))
            yield ErrorEvent(error=f"Reflection 流式调用失败: {exc}")
            return

        raw = "".join(content_parts).strip()
        data = parse_reflection_json(raw)
        if not data:
            reflection_log(
                "review_stream parse failed",
                raw_len=len(raw),
            )
            verdict = ReflectionVerdict(
                passed=False,
                summary="无法解析 ```reflection``` JSON",
                issues=[
                    ReflectionIssue(
                        severity="error",
                        category="review_failure",
                        message="模型未返回合法 reflection 块",
                    )
                ],
                recommendation="可重试审查或检查模型输出。",
                review_report=raw,
            )
        else:
            verdict = verdict_from_dict(data, review_report=raw)

        self.last_verdict = verdict
        elapsed_ms = int((time.monotonic() - start) * 1000)
        error_issues = sum(1 for i in verdict.issues if i.severity == "error")
        reflection_log(
            "review_stream done",
            passed=verdict.passed,
            issues=len(verdict.issues),
            error_issues=error_issues,
            recommendation_len=len(verdict.recommendation or ""),
            elapsed_ms=elapsed_ms,
        )
        yield ReflectionCompleteEvent(
            verdict=verdict,
            elapsed_ms=elapsed_ms,
        )

    def get_last_verdict(self) -> ReflectionVerdict | None:
        """上一轮 review 的结构化结论（供 Hub）。"""
        return self.last_verdict
