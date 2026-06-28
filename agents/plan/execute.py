"""PlanExecute Agent：规划 → 分发 → 汇总（可插拔组件骨架）。"""

from __future__ import annotations

import json
import re
import time
from collections.abc import AsyncIterator
from typing import Any, Protocol, runtime_checkable

from core.models import Message, Role
from core.provider import DeltaEvent, LLMProvider, StreamEndEvent, StreamErrorEvent

from agents.core.base import Agent
from agents.core.events import (
    AgentEvent,
    ErrorEvent,
    ExecutionResultEvent,
    FinalAnswerEvent,
    PlanCreatedEvent,
    PlanReadinessBlockedEvent,
    PlanReadyEvent,
    PlanTextDeltaEvent,
    RunStatsEvent,
    StepCompleteEvent,
    StepErrorEvent,
    StepOutputDeltaEvent,
    StepStartEvent,
)
from agents.core.intent import StructuredIntent
from agents.core.agent_log import clip, plan_log
from agents.plan.models import (
    ExecutionPlan,
    ExecutionResult,
    ExecutionStep,
    ExecutionStepTrace,
    StepStatus,
    SubTaskResult,
)
from agents.plan.step_args import resolve_step_tool_args_with_llm
from tools.param_readiness import check_plan_readiness, gaps_for_resolved_args, format_missing_args_message
from tools.registry import ToolRegistry
from tools.transport_errors import is_retryable_tool_error
from tools.runner import ToolRunner


# ── 可插拔协议 ─────────────────────────────────────────────


@runtime_checkable
class PlanGenerator(Protocol):
    """Plan 阶段：StructuredIntent → ExecutionPlan。"""

    async def create_plan(self, intent: StructuredIntent) -> ExecutionPlan: ...


@runtime_checkable
class AgentRegistry(Protocol):
    """专业 Agent 注册与解析。"""

    async def list_agents(self) -> list[dict[str, Any]]: ...

    async def resolve(self, agent_type: str) -> dict[str, Any] | None: ...


@runtime_checkable
class StepDelegate(Protocol):
    """Execute 阶段：将子任务分发给专业 Agent。"""

    async def delegate(
        self,
        *,
        step: ExecutionStep,
        agent_info: dict[str, Any],
        context: dict[str, Any],
    ) -> SubTaskResult: ...


@runtime_checkable
class ResultAggregator(Protocol):
    """汇总各步输出为 deliverable。"""

    async def aggregate(
        self,
        *,
        intent: StructuredIntent,
        plan: ExecutionPlan,
        trace: list[ExecutionStepTrace],
    ) -> str: ...


# ── 默认占位实现（便于后续替换） ───────────────────────────


class StubPlanGenerator:
    """占位计划生成器：优先按 suggested_tools 生成单步 MCP 计划，否则 legacy 单步。"""

    def __init__(self, tools: ToolRegistry | None = None) -> None:
        self._tools = tools

    async def create_plan(self, intent: StructuredIntent) -> ExecutionPlan:
        if self._tools is not None:
            known = {d["name"] for d in self._tools.list_definitions()}
            plan = plan_from_dict_tools(
                {}, intent=intent, known_tool_names=known
            )
            if plan.steps:
                plan.rationale = (
                    "StubPlanGenerator：按 suggested_tools 生成单步工具计划"
                )
                return plan

        return ExecutionPlan(
            task_type=intent.intent,
            rationale="StubPlanGenerator：无 LLM 的单步占位计划",
            steps=[
                ExecutionStep(
                    step_id=1,
                    agent_type="general",
                    task_description=intent.summary or intent.user_reply,
                    expected_output="子任务执行结果摘要",
                    dependencies=[],
                )
            ],
        )


_PLAN_JSON_BLOCK_RE = re.compile(
    r"```(?:json|plan)?\s*\n(.*?)\n```",
    re.DOTALL | re.IGNORECASE,
)

PLAN_GENERATION_SYSTEM_TOOLS = """你是灵枢 PlanExecute 的规划助手。根据已澄清的结构化意图与用户消息中的 **MCP 工具目录**，制定可执行的多步计划。

## 工具来源（必须遵守）
- 可调用工具由 MCP 从**当前接入的 API 目录**动态加载；换接入源后工具名、参数、数量都会变。
- **唯一权威来源**是用户消息里的「当前可用 MCP 工具」列表（含 name / description / parameters）。
- **禁止**凭训练记忆、历史对话或旧工具目录臆造 tool_name；列表里没有的工具只能写入 unfulfillable_steps。
- 选工具时：对照用户意图 ↔ 各工具的 description 与 parameters，自行判断调用哪些、顺序如何、参数从哪来（intent.slots、用户原话、或依赖前序步骤——前序结果由 Execute 提供，Plan 阶段勿写死响应字段路径）。

## 计划规则
- 每一步对应一个 MCP 工具；tool_name 必须与目录中某条的 name **完全一致**
- tool_args 须符合该条 parameters JSON Schema；已知参数从 intent.slots 提取，未知必填项勿瞎填占位值
- 用户给名称/地址/关键词而详情接口需要 ID 时：先调用搜索/列表类工具，再调用详情类工具；后者 dependencies 指向前者，tool_args 可留空由 Execute 从前序输出组装
- 无目录工具可覆盖的子任务 → unfulfillable_steps（说明原因），不要放进 steps
- steps 按 step_id 从 1 递增；dependencies 只能引用更小的 step_id
- intent.slots.suggested_tools 仅为 ReAct 提示，**必须**在目录中存在才采用；最终以目录 + 意图为准
- task_description / expected_output 写清本步目标；跨步依赖用 dependencies 表达，勿假设固定 API 响应结构
- 只输出 JSON，用 ```plan 代码块包裹：

```plan
{
  "task_type": "general_task",
  "rationale": "一句说明为何这样拆步",
  "steps": [
    {
      "step_id": 1,
      "tool_name": "工具名",
      "tool_args": {},
      "task_description": "…",
      "expected_output": "…",
      "dependencies": []
    }
  ],
  "unfulfillable_steps": [
    {"tool_name": "unknownTool", "reason": "无可用工具"}
  ]
}
```"""

PLAN_GENERATION_SYSTEM = """你是灵枢 PlanExecute 的规划助手。根据已澄清的结构化意图，制定可执行的多步计划。

规则：
- 每一步对应一种 agent_type，且必须来自「当前可用专业 Agent」列表
- 无可用 Agent 的类型写入 unfulfillable_steps，不要放进 steps
- steps 按 step_id 从 1 递增；dependencies 只能引用更小的 step_id
- task_description 具体可执行；expected_output 描述该步产出
- 单步可完成的任务（如简单 document_qa）可只生成 1 步
- 只输出 JSON，用 ```plan 代码块包裹：

```plan
{
  "task_type": "contract_drafting",
  "rationale": "一句说明为何这样拆步",
  "steps": [
    {
      "step_id": 1,
      "agent_type": "programming",
      "task_description": "…",
      "expected_output": "…",
      "dependencies": []
    }
  ],
  "unfulfillable_steps": [
    {"step_id": 0, "agent_type": "finance", "reason": "无可用 Agent"}
  ]
}
```"""


def parse_plan_json(text: str) -> dict[str, Any]:
    """从模型输出解析计划 JSON。"""
    raw = (text or "").strip()
    if not raw:
        return {}

    match = _PLAN_JSON_BLOCK_RE.search(raw)
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


def plan_from_dict(
    data: dict[str, Any],
    *,
    intent: StructuredIntent,
    registry: AgentRegistry | None = None,
    known_agent_types: set[str] | None = None,
) -> ExecutionPlan:
    """将解析后的 dict 转为 ExecutionPlan，并校验 agent_type。"""
    steps: list[ExecutionStep] = []
    unfulfillable: list[dict[str, Any]] = list(data.get("unfulfillable_steps") or [])

    for raw_step in data.get("steps") or []:
        if not isinstance(raw_step, dict):
            continue
        agent_type = str(raw_step.get("agent_type") or "").strip()
        if not agent_type:
            continue
        if known_agent_types is not None and agent_type not in known_agent_types:
            unfulfillable.append(
                {
                    "agent_type": agent_type,
                    "reason": "Registry 中无此类型",
                    "task_description": raw_step.get("task_description"),
                }
            )
            continue
        deps = raw_step.get("dependencies") or []
        if not isinstance(deps, list):
            deps = []
        steps.append(
            ExecutionStep(
                step_id=int(raw_step.get("step_id") or len(steps) + 1),
                agent_type=agent_type,
                task_description=str(
                    raw_step.get("task_description") or intent.summary
                ).strip(),
                expected_output=str(raw_step.get("expected_output") or "").strip(),
                dependencies=[int(d) for d in deps if isinstance(d, (int, float))],
            )
        )

    if not steps:
        steps.append(
            ExecutionStep(
                step_id=1,
                agent_type=next(iter(known_agent_types), "general"),
                task_description=intent.summary or intent.user_reply,
                expected_output="任务结果摘要",
                dependencies=[],
            )
        )

    return ExecutionPlan(
        task_type=str(data.get("task_type") or intent.intent),
        rationale=str(data.get("rationale") or ""),
        steps=steps,
        unfulfillable_steps=unfulfillable,
    )


def plan_from_dict_tools(
    data: dict[str, Any],
    *,
    intent: StructuredIntent,
    known_tool_names: set[str],
) -> ExecutionPlan:
    """将解析后的 dict 转为 ExecutionPlan，并校验 tool_name。"""
    steps: list[ExecutionStep] = []
    unfulfillable: list[dict[str, Any]] = list(data.get("unfulfillable_steps") or [])

    for raw_step in data.get("steps") or []:
        if not isinstance(raw_step, dict):
            continue
        tool_name = str(raw_step.get("tool_name") or "").strip()
        if not tool_name:
            continue
        if tool_name not in known_tool_names:
            unfulfillable.append(
                {
                    "tool_name": tool_name,
                    "reason": "Registry 中无此工具",
                    "task_description": raw_step.get("task_description"),
                }
            )
            continue
        tool_args = raw_step.get("tool_args") or {}
        if not isinstance(tool_args, dict):
            tool_args = {}
        deps = raw_step.get("dependencies") or []
        if not isinstance(deps, list):
            deps = []
        steps.append(
            ExecutionStep(
                step_id=int(raw_step.get("step_id") or len(steps) + 1),
                tool_name=tool_name,
                tool_args=tool_args,
                task_description=str(
                    raw_step.get("task_description") or intent.summary
                ).strip(),
                expected_output=str(raw_step.get("expected_output") or "").strip(),
                dependencies=[int(d) for d in deps if isinstance(d, (int, float))],
            )
        )

    if not steps:
        suggested = intent.slots.get("suggested_tools")
        if isinstance(suggested, list):
            for raw_name in suggested:
                name = str(raw_name).strip()
                if name not in known_tool_names:
                    continue
                args = intent.slots.get("action_params") or {}
                if not isinstance(args, dict):
                    args = {}
                steps.append(
                    ExecutionStep(
                        step_id=1,
                        tool_name=name,
                        tool_args=args,
                        task_description=intent.summary or intent.user_reply,
                        expected_output="工具调用结果",
                        dependencies=[],
                    )
                )
                break

    return ExecutionPlan(
        task_type=str(data.get("task_type") or intent.intent),
        rationale=str(data.get("rationale") or ""),
        steps=steps,
        unfulfillable_steps=unfulfillable,
    )


async def _plan_known_agent_types(registry: AgentRegistry | None) -> set[str]:
    if registry is None:
        return set()
    types: set[str] = set()
    for agent in await registry.list_agents():
        for cap in agent.get("capabilities") or []:
            types.add(str(cap))
        if agent.get("agent_type"):
            types.add(str(agent["agent_type"]))
    return types


def _format_tool_catalog(tools: ToolRegistry) -> str:
    lines: list[str] = []
    for definition in tools.list_definitions():
        name = str(definition.get("name") or "")
        desc = str(definition.get("description") or "").strip()
        params = json.dumps(definition.get("parameters") or {}, ensure_ascii=False)
        lines.append(f"- **{name}**：{desc}\n  parameters: {params}")
    return "\n".join(lines) if lines else "（无可用工具）"


_MCP_CATALOG_PREAMBLE = """\
下列工具由 MCP 注册表提供（随当前接入的 API 目录变化）。规划时只使用此列表中的 name；\
parameters 即各工具允许的 tool_args 形状。"""


def _plan_user_prompt_tools(intent: StructuredIntent, tools: ToolRegistry) -> str:
    catalog = _format_tool_catalog(tools)
    suggested = intent.slots.get("suggested_tools")
    hint = ""
    if suggested:
        hint = (
            f"\nReAct 建议的工具（须在下列目录中存在方可采用，否则忽略）："
            f"{json.dumps(suggested, ensure_ascii=False)}\n"
        )
    return (
        f"{_MCP_CATALOG_PREAMBLE}\n\n"
        f"当前可用 MCP 工具：\n{catalog}\n"
        f"{hint}\n"
        f"结构化意图：\n{json.dumps(intent.to_dict(), ensure_ascii=False, indent=2)}\n\n"
        "请仅依据上述目录与意图输出 ```plan``` JSON。"
    )


def _plan_messages_tools(intent: StructuredIntent, tools: ToolRegistry) -> list[Message]:
    return [
        Message(role=Role.SYSTEM, content=PLAN_GENERATION_SYSTEM_TOOLS),
        Message(role=Role.USER, content=_plan_user_prompt_tools(intent, tools)),
    ]


def _plan_user_prompt(intent: StructuredIntent, known: set[str]) -> str:
    if known:
        agents_blurb = "当前可用专业 Agent 类型：" + ", ".join(sorted(known))
    else:
        agents_blurb = "（未提供 Registry，agent_type 请使用 programming / legal / general 等常见类型）"
    return (
        f"{agents_blurb}\n\n"
        f"结构化意图：\n{json.dumps(intent.to_dict(), ensure_ascii=False, indent=2)}\n\n"
        "请输出 ```plan``` JSON。"
    )


def _plan_messages(intent: StructuredIntent, known: set[str]) -> list[Message]:
    return [
        Message(role=Role.SYSTEM, content=PLAN_GENERATION_SYSTEM),
        Message(role=Role.USER, content=_plan_user_prompt(intent, known)),
    ]


class LLMPlanGenerator:
    """Plan 阶段：调用 LLM 根据 StructuredIntent 生成 ExecutionPlan。"""

    def __init__(
        self,
        llm: LLMProvider,
        registry: AgentRegistry | None = None,
        tools: ToolRegistry | None = None,
        *,
        fallback: PlanGenerator | None = None,
    ) -> None:
        self._llm = llm
        self._registry = registry
        self._tools = tools
        self._fallback = fallback or StubPlanGenerator(tools=tools)

    def _uses_tools(self) -> bool:
        if self._tools is None:
            return False
        return bool(self._tools.list_definitions())

    def _known_tool_names(self) -> set[str]:
        if self._tools is None:
            return set()
        return {d["name"] for d in self._tools.list_definitions()}

    async def _known_agent_types(self) -> set[str]:
        return await _plan_known_agent_types(self._registry)

    async def create_plan_stream(
        self, intent: StructuredIntent
    ) -> AsyncIterator[AgentEvent]:
        """流式生成计划：先产出原始 JSON 增量，最后产出 PlanReadyEvent。"""
        if self._uses_tools():
            known_tools = self._known_tool_names()
            messages = _plan_messages_tools(intent, self._tools)  # type: ignore[arg-type]
            plan_log(
                "create_plan_stream start",
                intent=intent.intent,
                mode="tools",
                known_tools=len(known_tools),
            )
        else:
            known = await self._known_agent_types()
            messages = _plan_messages(intent, known)
            plan_log(
                "create_plan_stream start",
                intent=intent.intent,
                mode="agents",
                known_agents=len(known),
            )
        content_parts: list[str] = []
        try:
            async for ev in self._llm.generate_stream(messages=messages, tools=None):
                if isinstance(ev, DeltaEvent):
                    content_parts.append(ev.delta)
                    yield PlanTextDeltaEvent(delta=ev.delta)
                elif isinstance(ev, StreamEndEvent):
                    if ev.output.content:
                        content_parts = [ev.output.content]
                elif isinstance(ev, StreamErrorEvent):
                    plan_log(
                        "create_plan_stream llm error; fallback",
                        error=str(ev.error),
                    )
                    yield ErrorEvent(error=str(ev.error))
                    plan = await self._fallback.create_plan(intent)
                    yield PlanReadyEvent(plan=plan)
                    return
        except Exception as exc:
            plan_log(
                "create_plan_stream failed; fallback",
                error=str(exc),
            )
            yield ErrorEvent(error=f"计划流式生成失败: {exc}")
            plan = await self._fallback.create_plan(intent)
            yield PlanReadyEvent(plan=plan)
            return

        raw = "".join(content_parts).strip()
        data = parse_plan_json(raw)
        if not data.get("steps"):
            plan_log(
                "create_plan_stream parse empty; fallback",
                raw_len=len(raw),
            )
            plan = await self._fallback.create_plan(intent)
        elif self._uses_tools():
            plan = plan_from_dict_tools(
                data,
                intent=intent,
                known_tool_names=self._known_tool_names(),
            )
            plan_log(
                "create_plan_stream ready",
                steps=len(plan.steps),
                task_type=plan.task_type,
            )
        else:
            known = await self._known_agent_types()
            plan = plan_from_dict(
                data,
                intent=intent,
                registry=self._registry,
                known_agent_types=known or None,
            )
            plan_log(
                "create_plan_stream ready",
                steps=len(plan.steps),
                task_type=plan.task_type,
            )
        yield PlanReadyEvent(plan=plan)

    async def create_plan(self, intent: StructuredIntent) -> ExecutionPlan:
        if self._uses_tools():
            known_tools = self._known_tool_names()
            messages = _plan_messages_tools(intent, self._tools)  # type: ignore[arg-type]
            plan_log("create_plan start", intent=intent.intent, mode="tools")
        else:
            known = await self._known_agent_types()
            messages = _plan_messages(intent, known)
            plan_log("create_plan start", intent=intent.intent, mode="agents")
        try:
            out = await self._llm.generate(
                messages=messages,
                tools=None,
            )
            data = parse_plan_json(out.content or "")
        except Exception as exc:
            plan_log("create_plan failed; fallback", error=str(exc))
            return await self._fallback.create_plan(intent)

        if not data.get("steps"):
            plan_log("create_plan parse empty; fallback")
            return await self._fallback.create_plan(intent)

        if self._uses_tools():
            plan = plan_from_dict_tools(
                data,
                intent=intent,
                known_tool_names=self._known_tool_names(),
            )
        else:
            known = await self._known_agent_types()
            plan = plan_from_dict(
                data,
                intent=intent,
                registry=self._registry,
                known_agent_types=known or None,
            )
        plan_log("create_plan ready", steps=len(plan.steps))
        return plan


class InMemoryAgentRegistry:
    """内存 Agent 注册表（可运行时 register）。"""

    def __init__(self, agents: list[dict[str, Any]] | None = None) -> None:
        self._agents: list[dict[str, Any]] = list(agents or [])

    def register(self, agent: dict[str, Any]) -> None:
        self._agents.append(agent)

    async def list_agents(self) -> list[dict[str, Any]]:
        return [dict(a) for a in self._agents]

    async def resolve(self, agent_type: str) -> dict[str, Any] | None:
        for agent in self._agents:
            caps = agent.get("capabilities") or []
            if agent_type in caps or agent.get("agent_type") == agent_type:
                return dict(agent)
        return None


class StubStepDelegate:
    """占位分发：标记为 skipped，不调用真实专业 Agent。"""

    async def delegate(
        self,
        *,
        step: ExecutionStep,
        agent_info: dict[str, Any],
        context: dict[str, Any],
    ) -> SubTaskResult:
        _ = agent_info, context
        return SubTaskResult(
            success=False,
            content="",
            error="StubStepDelegate：尚未接入 delegate_task",
            agent_id=None,
        )


def expand_rerun_step_ids(plan: ExecutionPlan, step_ids: list[int]) -> set[int]:
    """将需重跑的步骤扩展为包含所有下游依赖步骤。"""
    rerun = {sid for sid in step_ids if sid > 0}
    if not rerun:
        return rerun
    while True:
        added = False
        for step in plan.steps:
            if step.step_id in rerun:
                continue
            if any(dep in rerun for dep in step.dependencies):
                rerun.add(step.step_id)
                added = True
        if not added:
            break
    return rerun


class DefaultResultAggregator:
    """按步骤顺序拼接成功与失败步骤产出（部分成功时须包含失败原因）。"""

    async def aggregate(
        self,
        *,
        intent: StructuredIntent,
        plan: ExecutionPlan,
        trace: list[ExecutionStepTrace],
    ) -> str:
        _ = intent, plan
        from tools.transport_errors import format_step_failure

        if not trace:
            return "（暂无执行产出，请检查工具调用或 StepDelegate 配置）"

        parts: list[str] = []
        for row in sorted(trace, key=lambda t: t.step_id):
            if row.status == StepStatus.SUCCESS:
                body = (row.output or "").strip()
                if not body:
                    body = (row.task_description or "").strip()
                if not body:
                    body = f"步骤 {row.step_id} 已完成"
                parts.append(f"## 步骤 {row.step_id} · 成功\n{body}")
            elif row.status == StepStatus.FAILED:
                err = format_step_failure(
                    row.error or "工具执行失败",
                    tool_name=row.tool_name or "",
                )
                parts.append(f"## 步骤 {row.step_id} · 失败\n{err}")
            elif row.status == StepStatus.SKIPPED:
                parts.append(
                    f"## 步骤 {row.step_id} · 跳过\n"
                    f"{(row.error or '依赖未满足').strip()}"
                )

        if parts:
            return "\n\n".join(parts)

        return "（暂无执行产出，请检查工具调用或 StepDelegate 配置）"


_DEFAULT_SYSTEM = """你是灵枢（Agent Cortex）PlanExecute 规划执行层。

本阶段根据 StructuredIntent 制定计划并按步执行。MCP 模式下工具来自当前运行时注册表（非固定 API）；\
Plan 与 Execute 均以运行时工具目录为准，不假设具体接口或业务名称。"""


class PlanExecuteAgent(Agent):
    """
    PlanExecute Agent 骨架。

    主入口：
        - ``execute(intent)`` → ``ExecutionResult``
        - ``execute_stream(intent)`` → 事件流

    可插拔：
        - ``plan_generator`` / ``tool_runner``（MCP 直接执行）
        - ``registry`` / ``step_delegate``（legacy 专业 Agent 分发）
        - ``aggregator``
    """

    def __init__(
        self,
        llm: LLMProvider,
        *,
        system_prompt: str | None = None,
        memory_manager: Any = None,
        plan_generator: PlanGenerator | None = None,
        tool_runner: ToolRunner | None = None,
        registry: AgentRegistry | None = None,
        step_delegate: StepDelegate | None = None,
        aggregator: ResultAggregator | None = None,
        step_timeout_retry: int = 1,
    ) -> None:
        super().__init__(
            llm,
            system_prompt=(system_prompt or _DEFAULT_SYSTEM).strip(),
            memory_manager=memory_manager,
        )
        self.plan_generator = plan_generator or StubPlanGenerator()
        self.tool_runner = tool_runner
        self.registry = registry or InMemoryAgentRegistry()
        self.step_delegate = step_delegate or StubStepDelegate()
        self.aggregator = aggregator or DefaultResultAggregator()
        self.step_timeout_retry = max(0, step_timeout_retry)
        self.last_result: ExecutionResult | None = None

    async def execute(self, intent: StructuredIntent) -> ExecutionResult:
        """非流式执行：Plan → Execute → Aggregate。"""
        final: ExecutionResult | None = None
        async for ev in self.execute_stream(intent):
            if isinstance(ev, ExecutionResultEvent):
                final = ev.result
            if isinstance(ev, ErrorEvent):
                return ExecutionResult(
                    deliverable=f"执行失败：{ev.error}",
                    partial_success=False,
                    source_intent=intent,
                )
        return final or ExecutionResult(
            deliverable="未产生 ExecutionResult",
            source_intent=intent,
        )

    async def execute_stream(
        self,
        intent: StructuredIntent,
        *,
        plan: ExecutionPlan | None = None,
        skip_plan_generation: bool = False,
        revision_feedback: str = "",
        rerun_step_ids: list[int] | None = None,
        prior_outputs: dict[int, str] | None = None,
    ) -> AsyncIterator[AgentEvent]:
        """流式执行，产出 Plan / Step / Result 事件。

        Args:
            intent: ReAct 输出的结构化意图。
            plan: 若已生成计划，传入后可跳过 Plan 阶段（与 skip_plan_generation 配合）。
            skip_plan_generation: 为 True 时必须提供 plan，只跑 Execute 分发。
            revision_feedback: Reflection 打回时的修改说明（注入专业 Agent 上下文）。
            rerun_step_ids: 指定重跑的 step_id；未列出的步骤沿用 prior_outputs。
            prior_outputs: 上一轮成功步骤的 output，供修订时复用。
        """
        if not intent.is_clear:
            yield ErrorEvent(
                error="StructuredIntent.is_clear 为 false，不应进入 PlanExecute"
            )
            return
        if not intent.should_invoke_plan():
            yield ErrorEvent(error=f"intent={intent.intent!r} 无需进入 PlanExecute")
            return
        if skip_plan_generation and plan is None:
            yield ErrorEvent(error="skip_plan_generation 为 True 时必须传入 plan")
            return
        if rerun_step_ids is not None:
            if plan is None:
                yield ErrorEvent(error="修订重跑必须传入 plan")
                return
            if not skip_plan_generation:
                yield ErrorEvent(
                    error="修订重跑须 skip_plan_generation=True 且传入既有 plan"
                )
                return

        start = time.monotonic()
        tool_calls = 0
        tool_errors = 0

        plan_log(
            "execute_stream start",
            intent=intent.intent,
            skip_plan=skip_plan_generation,
            revision=bool((revision_feedback or "").strip()),
            rerun=rerun_step_ids is not None,
        )

        if plan is None:
            try:
                plan = await self.plan_generator.create_plan(intent)
            except Exception as exc:
                plan_log("execute_stream plan failed", error=str(exc))
                yield ErrorEvent(error=f"计划生成失败: {exc}")
                return

        rerun_set: set[int] | None = None
        if rerun_step_ids is not None:
            rerun_set = expand_rerun_step_ids(plan, rerun_step_ids)

        yield PlanCreatedEvent(steps=[s.to_dict() for s in plan.steps])
        plan_log("plan created", steps=len(plan.steps), task_type=plan.task_type)

        if self.tool_runner is not None and plan.steps:
            readiness = check_plan_readiness(
                plan,
                self.tool_runner.tools,
                step_filter=rerun_set,
                task_summary=intent.summary or intent.user_reply,
            )
            if not readiness.ready:
                plan_log(
                    "gate_b blocked",
                    gaps=len(readiness.gaps),
                    tools=sorted({g.tool_name for g in readiness.gaps}),
                )
                yield PlanReadinessBlockedEvent(
                    verdict=readiness,
                    clarify_message=readiness.clarify_message,
                    plan=plan,
                )
                return

        completed_outputs: dict[int, str] = dict(prior_outputs or {})
        trace: list[ExecutionStepTrace] = []
        feedback = (revision_feedback or "").strip()

        for step in sorted(plan.steps, key=lambda s: s.step_id):
            if rerun_set is not None and step.step_id not in rerun_set:
                if step.step_id in completed_outputs:
                    plan_log(
                        "step reuse prior",
                        step_id=step.step_id,
                        agent_type=step.agent_type,
                    )
                    row = ExecutionStepTrace(
                        step_id=step.step_id,
                        tool_name=step.tool_name,
                        agent_type=step.tool_name or step.agent_type,
                        status=StepStatus.SUCCESS,
                        task_description=step.task_description,
                        output=completed_outputs[step.step_id],
                    )
                    trace.append(row)
                    yield StepStartEvent(
                        step_id=step.step_id,
                        description=f"（沿用上一轮）{step.task_description}",
                        agent_type=step.tool_name or step.agent_type,
                        agent_id=step.tool_name or "",
                    )
                    yield StepCompleteEvent(
                        step_id=step.step_id,
                        summary=completed_outputs[step.step_id],
                    )
                    continue
                blockers = [
                    dep for dep in step.dependencies if dep not in completed_outputs
                ]
                if blockers:
                    plan_log(
                        "step skipped",
                        step_id=step.step_id,
                        reason="deps_in_rerun_branch",
                        blockers=blockers,
                    )
                    row = ExecutionStepTrace(
                        step_id=step.step_id,
                        tool_name=step.tool_name,
                        agent_type=step.tool_name or step.agent_type,
                        status=StepStatus.SKIPPED,
                        task_description=step.task_description,
                        error=f"依赖步骤未完成: {blockers}",
                    )
                    trace.append(row)
                    yield StepErrorEvent(
                        step_id=step.step_id,
                        error=row.error or "依赖未满足",
                    )
                continue
            blockers = [
                dep for dep in step.dependencies if dep not in completed_outputs
            ]
            if blockers:
                plan_log(
                    "step skipped",
                    step_id=step.step_id,
                    blockers=blockers,
                )
                row = ExecutionStepTrace(
                    step_id=step.step_id,
                    tool_name=step.tool_name,
                    agent_type=step.tool_name or step.agent_type,
                    status=StepStatus.SKIPPED,
                    task_description=step.task_description,
                    error=f"依赖步骤未完成: {blockers}",
                )
                trace.append(row)
                yield StepErrorEvent(
                    step_id=step.step_id,
                    error=row.error or "依赖未满足",
                )
                continue

            if self.tool_runner is not None:
                label = step.tool_name or step.agent_type
                if not step.tool_name:
                    plan_log("step no tool", step_id=step.step_id)
                    row = ExecutionStepTrace(
                        step_id=step.step_id,
                        tool_name=step.tool_name,
                        agent_type=label,
                        status=StepStatus.SKIPPED,
                        task_description=step.task_description,
                        error="计划中未指定 tool_name",
                    )
                    trace.append(row)
                    yield StepErrorEvent(
                        step_id=step.step_id,
                        error=row.error or "未指定工具",
                    )
                    continue
                if self.tool_runner.tools.get(step.tool_name) is None:
                    plan_log(
                        "step tool missing",
                        step_id=step.step_id,
                        tool_name=step.tool_name,
                    )
                    row = ExecutionStepTrace(
                        step_id=step.step_id,
                        tool_name=step.tool_name,
                        agent_type=label,
                        status=StepStatus.SKIPPED,
                        task_description=step.task_description,
                        error=f"无可用工具: {step.tool_name}",
                    )
                    trace.append(row)
                    yield StepErrorEvent(
                        step_id=step.step_id,
                        error=row.error or "无可用工具",
                    )
                    continue

                yield StepStartEvent(
                    step_id=step.step_id,
                    description=step.task_description,
                    agent_type=label,
                    agent_id=step.tool_name,
                )
                plan_log(
                    "tool step start",
                    step_id=step.step_id,
                    tool_name=step.tool_name,
                )
                step_start = time.monotonic()
                resolved_args = await self._resolve_step_tool_args(
                    step,
                    intent=intent,
                    completed_outputs=completed_outputs,
                )
                tool_def = self.tool_runner.tools.get(step.tool_name)
                arg_gaps: list = []
                if tool_def is not None:
                    arg_gaps = gaps_for_resolved_args(
                        step.step_id,
                        step.tool_name,
                        tool_def.parameters,
                        resolved_args,
                    )
                if arg_gaps:
                    output_text = format_missing_args_message(arg_gaps)
                    is_err = True
                    plan_log(
                        "tool step blocked",
                        step_id=step.step_id,
                        tool_name=step.tool_name,
                        missing=[g.param_name for g in arg_gaps],
                    )
                else:
                    output_text, is_err = await self._run_tool_step_with_retry(
                        step, tool_args=resolved_args
                    )
                tool_calls += 1
                if is_err:
                    tool_errors += 1
                elapsed = int((time.monotonic() - step_start) * 1000)
                if not is_err:
                    plan_log(
                        "tool step done",
                        step_id=step.step_id,
                        success=True,
                        output_len=len(output_text or ""),
                        elapsed_ms=elapsed,
                    )
                    completed_outputs[step.step_id] = output_text
                    row = ExecutionStepTrace(
                        step_id=step.step_id,
                        tool_name=step.tool_name,
                        agent_type=label,
                        status=StepStatus.SUCCESS,
                        task_description=step.task_description,
                        agent_id=step.tool_name,
                        output=output_text,
                        elapsed_ms=elapsed,
                    )
                    trace.append(row)
                    yield StepCompleteEvent(
                        step_id=step.step_id,
                        summary=output_text or "",
                    )
                else:
                    plan_log(
                        "tool step done",
                        step_id=step.step_id,
                        success=False,
                        error=clip(output_text, 120),
                        elapsed_ms=elapsed,
                    )
                    row = ExecutionStepTrace(
                        step_id=step.step_id,
                        tool_name=step.tool_name,
                        agent_type=label,
                        status=StepStatus.FAILED,
                        task_description=step.task_description,
                        agent_id=step.tool_name,
                        error=output_text or "工具执行失败",
                        elapsed_ms=elapsed,
                    )
                    trace.append(row)
                    yield StepErrorEvent(
                        step_id=step.step_id,
                        error=row.error or "工具执行失败",
                    )
                continue

            agent_info = await self.registry.resolve(step.agent_type)
            if agent_info is None:
                plan_log(
                    "step no agent",
                    step_id=step.step_id,
                    agent_type=step.agent_type,
                )
                row = ExecutionStepTrace(
                    step_id=step.step_id,
                    agent_type=step.agent_type,
                    status=StepStatus.SKIPPED,
                    task_description=step.task_description,
                    error=f"无可用 Agent 类型: {step.agent_type}",
                )
                trace.append(row)
                yield StepErrorEvent(
                    step_id=step.step_id,
                    error=row.error or "无可用 Agent",
                )
                continue

            yield StepStartEvent(
                step_id=step.step_id,
                description=step.task_description,
                agent_type=step.agent_type,
                agent_id=str(agent_info.get("agent_id") or ""),
            )
            context = {
                "intent": intent.to_dict(),
                "plan_task_type": plan.task_type,
                "dependency_outputs": {
                    dep: completed_outputs[dep] for dep in step.dependencies
                },
                "step": step.to_dict(),
                "revision_feedback": feedback,
                "is_revision": rerun_set is not None and step.step_id in rerun_set,
            }
            plan_log(
                "step start",
                step_id=step.step_id,
                agent_type=step.agent_type,
                is_revision=context["is_revision"],
            )

            step_start = time.monotonic()
            sub_result: SubTaskResult | None = None
            async for stream_ev in self._run_step_with_retry_stream(
                step, agent_info, context
            ):
                if isinstance(stream_ev, StepOutputDeltaEvent):
                    yield stream_ev
                elif isinstance(stream_ev, SubTaskResult):
                    sub_result = stream_ev
            if sub_result is None:
                sub_result = SubTaskResult(success=False, error="步骤未返回结果")
            tool_calls += 1
            if not sub_result.success:
                tool_errors += 1

            elapsed = int((time.monotonic() - step_start) * 1000)
            if sub_result.success:
                plan_log(
                    "step done",
                    step_id=step.step_id,
                    success=True,
                    output_len=len(sub_result.content or ""),
                    elapsed_ms=sub_result.elapsed_ms or elapsed,
                )
                completed_outputs[step.step_id] = sub_result.content
                row = ExecutionStepTrace(
                    step_id=step.step_id,
                    tool_name=step.tool_name,
                    agent_type=step.tool_name or step.agent_type,
                    status=StepStatus.SUCCESS,
                    task_description=step.task_description,
                    agent_id=sub_result.agent_id or agent_info.get("agent_id"),
                    output=sub_result.content,
                    elapsed_ms=sub_result.elapsed_ms or elapsed,
                )
                trace.append(row)
                yield StepCompleteEvent(
                    step_id=step.step_id,
                    summary=sub_result.content or "",
                )
            else:
                plan_log(
                    "step done",
                    step_id=step.step_id,
                    success=False,
                    error=clip(sub_result.error, 120),
                    elapsed_ms=sub_result.elapsed_ms or elapsed,
                )
                row = ExecutionStepTrace(
                    step_id=step.step_id,
                    tool_name=step.tool_name,
                    agent_type=step.tool_name or step.agent_type,
                    status=StepStatus.FAILED,
                    task_description=step.task_description,
                    agent_id=sub_result.agent_id,
                    error=sub_result.error or "执行失败",
                    elapsed_ms=sub_result.elapsed_ms or elapsed,
                )
                trace.append(row)
                yield StepErrorEvent(
                    step_id=step.step_id,
                    error=row.error or "执行失败",
                )

        try:
            deliverable = await self.aggregator.aggregate(
                intent=intent, plan=plan, trace=trace
            )
        except Exception as exc:
            plan_log("aggregate failed", error=str(exc))
            yield ErrorEvent(error=f"结果汇总失败: {exc}")
            return

        success_count = sum(1 for t in trace if t.status == StepStatus.SUCCESS)
        partial = 0 < success_count < len(plan.steps) if plan.steps else False

        result = ExecutionResult(
            deliverable=deliverable,
            trace=trace,
            partial_success=partial,
            plan=plan,
            source_intent=intent,
        )
        self.last_result = result

        elapsed_ms = int((time.monotonic() - start) * 1000)
        plan_log(
            "execute_stream done",
            deliverable_len=len(deliverable or ""),
            success_steps=success_count,
            total_steps=len(plan.steps),
            partial=partial,
            elapsed_ms=elapsed_ms,
        )
        yield RunStatsEvent(
            steps=len(plan.steps),
            tool_calls=tool_calls,
            tool_errors=tool_errors,
            elapsed_ms=elapsed_ms,
        )
        yield ExecutionResultEvent(result=result)
        yield FinalAnswerEvent(content=deliverable)

    async def _resolve_step_tool_args(
        self,
        step: ExecutionStep,
        *,
        intent: StructuredIntent,
        completed_outputs: dict[int, str],
    ) -> dict[str, Any]:
        plan_args = dict(step.tool_args or {})
        if self.tool_runner is None:
            return plan_args
        tool = self.tool_runner.tools.get(step.tool_name)
        if tool is None:
            return plan_args
        if not step.dependencies:
            return plan_args

        dependency_outputs = {
            dep: completed_outputs[dep]
            for dep in step.dependencies
            if dep in completed_outputs
        }
        return await resolve_step_tool_args_with_llm(
            self.llm,
            step=step,
            parameters=tool.parameters,
            intent=intent,
            dependency_outputs=dependency_outputs,
            plan_hint=plan_args,
        )

    async def _run_tool_step_with_retry(
        self,
        step: ExecutionStep,
        *,
        tool_args: dict[str, Any] | None = None,
    ) -> tuple[str, bool]:
        """直接调用 MCP 工具，带重试。返回 (output, is_error)。"""
        if self.tool_runner is None:
            return "ToolRunner 未配置", True
        payload = dict(tool_args if tool_args is not None else step.tool_args)
        last_text = ""
        attempts = 1 + self.step_timeout_retry
        for attempt in range(attempts):
            last_text, is_err = await self.tool_runner.run(
                step.tool_name, payload
            )
            if not is_err:
                return last_text, False
            if not is_retryable_tool_error(last_text):
                plan_log(
                    "tool step no retry",
                    step_id=step.step_id,
                    reason="non_retryable",
                    error=clip(last_text, 120),
                )
                return last_text, True
            if attempt + 1 < attempts:
                plan_log(
                    "tool step retry",
                    step_id=step.step_id,
                    attempt=attempt + 1,
                    error=clip(last_text, 80),
                )
        return last_text or "工具执行失败", True

    async def _run_step_with_retry(
        self,
        step: ExecutionStep,
        agent_info: dict[str, Any],
        context: dict[str, Any],
    ) -> SubTaskResult:
        last: SubTaskResult | None = None
        attempts = 1 + self.step_timeout_retry
        for attempt in range(attempts):
            last = await self.step_delegate.delegate(
                step=step,
                agent_info=agent_info,
                context=context,
            )
            if last.success:
                return last
            if attempt + 1 < attempts:
                plan_log(
                    "step retry",
                    step_id=step.step_id,
                    attempt=attempt + 1,
                    error=clip(last.error, 80),
                )
        return last or SubTaskResult(success=False, error="未知错误")

    async def _run_step_with_retry_stream(
        self,
        step: ExecutionStep,
        agent_info: dict[str, Any],
        context: dict[str, Any],
    ) -> AsyncIterator[StepOutputDeltaEvent | SubTaskResult]:
        """优先流式 delegate_stream，否则回退为单次 delegate。"""
        stream_fn = getattr(self.step_delegate, "delegate_stream", None)
        if stream_fn is None:
            result = await self._run_step_with_retry(step, agent_info, context)
            yield result
            return

        last: SubTaskResult | None = None
        attempts = 1 + self.step_timeout_retry
        for attempt in range(attempts):
            last = None
            async for item in stream_fn(
                step=step,
                agent_info=agent_info,
                context=context,
            ):
                if isinstance(item, StepOutputDeltaEvent):
                    yield item
                elif isinstance(item, SubTaskResult):
                    last = item
            if last is not None and last.success:
                yield last
                return
            if attempt + 1 < attempts:
                plan_log(
                    "step retry",
                    step_id=step.step_id,
                    attempt=attempt + 1,
                    error=clip(last.error if last else "", 80),
                )
        yield last or SubTaskResult(success=False, error="未知错误")

    def get_last_result(self) -> ExecutionResult | None:
        """上一轮 execute 的完整结果（供 Reflection / Hub）。"""
        return self.last_result

    async def run(self, task: str) -> AgentEvent:
        """兼容 Agent 基类：请使用 ``execute(StructuredIntent)``。"""
        _ = task
        return ErrorEvent(
            error="PlanExecuteAgent 请使用 execute(intent=StructuredIntent)"
        )

    async def run_stream(self, task: str) -> AsyncIterator[AgentEvent]:
        """兼容 Agent 基类：请使用 ``execute_stream(StructuredIntent)``。"""
        _ = task
        yield ErrorEvent(
            error="PlanExecuteAgent 请使用 execute_stream(intent=StructuredIntent)"
        )
