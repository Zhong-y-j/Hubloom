"""Execute 阶段：根据依赖步骤输出组装 MCP 工具参数。"""

from __future__ import annotations

import json
import re
from typing import Any

from core.models import Message, Role
from core.provider import LLMProvider

from agents.core.agent_log import clip, plan_log
from agents.core.intent import StructuredIntent
from agents.plan.models import ExecutionStep

_JSON_BLOCK_RE = re.compile(
    r"```(?:json)?\s*\n(.*?)\n```",
    re.DOTALL | re.IGNORECASE,
)

_STEP_ARGS_SYSTEM = """你是 PlanExecute 的工具参数组装助手。

根据工具的 JSON Schema parameters、本步任务描述、用户结构化意图，以及已完成步骤的原始输出，
生成本步 MCP 工具调用的参数 JSON 对象。

规则：
- 只输出一个 JSON 对象，不要 markdown 解释
- 键名必须来自 parameters.properties
- required 字段必须齐全且类型合理
- 从依赖步骤输出中提取 ID、列表项等；列表多条时按用户原意选最匹配的一条
- 若 Plan 已给出 plan_hint 且合理，可沿用或补充
- 不要编造用户未提及且无法从依赖输出推断的值
"""


def filter_tool_args(parameters: dict[str, Any], args: dict[str, Any]) -> dict[str, Any]:
    props = parameters.get("properties") if isinstance(parameters, dict) else None
    if not isinstance(props, dict) or not props:
        return dict(args)
    allowed = set(props.keys())
    return {k: v for k, v in args.items() if k in allowed}


def _parse_json_object(text: str) -> dict[str, Any]:
    raw = (text or "").strip()
    if not raw:
        return {}
    match = _JSON_BLOCK_RE.search(raw)
    payload = match.group(1).strip() if match else raw
    try:
        data = json.loads(payload)
    except json.JSONDecodeError:
        return {}
    return data if isinstance(data, dict) else {}


def _format_dependency_outputs(dependency_outputs: dict[int, str]) -> str:
    if not dependency_outputs:
        return "（无）"
    parts: list[str] = []
    for step_id in sorted(dependency_outputs):
        body = (dependency_outputs[step_id] or "").strip()
        if len(body) > 4000:
            body = body[:4000] + "\n…（已截断）"
        parts.append(f"### 步骤 {step_id} 输出\n{body or '（空）'}")
    return "\n\n".join(parts)


async def resolve_step_tool_args_with_llm(
    llm: LLMProvider,
    *,
    step: ExecutionStep,
    parameters: dict[str, Any],
    intent: StructuredIntent,
    dependency_outputs: dict[int, str],
    plan_hint: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """对有 dependencies 的步骤，用 LLM 从 prior outputs 组装 tool_args。"""
    user_content = (
        f"工具名：{step.tool_name}\n"
        f"parameters schema：\n"
        f"{json.dumps(parameters, ensure_ascii=False, indent=2)}\n\n"
        f"本步任务：{step.task_description}\n"
        f"期望产出：{step.expected_output or '（未指定）'}\n\n"
        f"用户意图：\n{json.dumps(intent.to_dict(), ensure_ascii=False, indent=2)}\n\n"
        f"依赖步骤输出：\n{_format_dependency_outputs(dependency_outputs)}\n\n"
        f"Plan 提示参数 plan_hint：\n"
        f"{json.dumps(plan_hint or {}, ensure_ascii=False, indent=2)}\n\n"
        "请输出本步 tool_args JSON 对象。"
    )
    messages = [
        Message(role=Role.SYSTEM, content=_STEP_ARGS_SYSTEM),
        Message(role=Role.USER, content=user_content),
    ]
    plan_log(
        "step args llm start",
        step_id=step.step_id,
        tool_name=step.tool_name,
        deps=sorted(dependency_outputs),
    )
    try:
        out = await llm.generate(messages=messages, tools=None)
        raw_args = _parse_json_object(out.content or "")
    except Exception as exc:
        plan_log(
            "step args llm failed",
            step_id=step.step_id,
            error=clip(str(exc), 120),
        )
        raw_args = dict(plan_hint or {})

    filtered = filter_tool_args(parameters, raw_args)
    plan_log(
        "step args llm done",
        step_id=step.step_id,
        tool_name=step.tool_name,
        arg_keys=sorted(filtered.keys()),
    )
    return filtered
