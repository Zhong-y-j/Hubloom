"""Plan 执行前必填参数校验（Gate B）。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from agents.plan.models import ExecutionPlan, ExecutionStep
from tools.registry import ToolRegistry

_DEFERRED_PLACEHOLDER_MARKERS = ("{{", "}}")


@dataclass(frozen=True)
class ParamGap:
    step_id: int
    tool_name: str
    param_name: str
    label: str
    description: str = ""


@dataclass(frozen=True)
class PlanReadinessVerdict:
    ready: bool
    gaps: tuple[ParamGap, ...] = ()
    clarify_message: str = ""


def is_present(value: Any) -> bool:
    """None / 空字符串视为缺失；0、False、[] 视为已提供。"""
    if value is None:
        return False
    if isinstance(value, str) and value.strip() == "":
        return False
    return True


def is_deferred_arg(value: Any) -> bool:
    """Plan 占位符（由 Execute 解析），Gate B 放行。"""
    if not isinstance(value, str):
        return False
    text = value.strip()
    return bool(text) and all(marker in text for marker in _DEFERRED_PLACEHOLDER_MARKERS)


def missing_required_fields(parameters: dict[str, Any], args: dict[str, Any]) -> list[str]:
    required = parameters.get("required") or []
    if not isinstance(required, list):
        return []
    missing: list[str] = []
    for key in required:
        if not isinstance(key, str):
            continue
        if key not in args:
            missing.append(key)
            continue
        value = args[key]
        if is_deferred_arg(value):
            continue
        if not is_present(value):
            missing.append(key)
    return missing


def describe_param(parameters: dict[str, Any], param_name: str) -> tuple[str, str]:
    props = parameters.get("properties") or {}
    if not isinstance(props, dict):
        return param_name, ""
    schema = props.get(param_name) or {}
    if not isinstance(schema, dict):
        return param_name, ""
    label = str(schema.get("title") or param_name).strip() or param_name
    description = str(schema.get("description") or "").strip()
    return label, description


def check_step(
    step: ExecutionStep,
    tool_def: dict[str, Any],
) -> list[ParamGap]:
    if step.dependencies:
        return []
    parameters = tool_def.get("parameters") or {}
    if not isinstance(parameters, dict):
        parameters = {}
    args = step.tool_args if isinstance(step.tool_args, dict) else {}
    gaps: list[ParamGap] = []
    for param_name in missing_required_fields(parameters, args):
        label, description = describe_param(parameters, param_name)
        gaps.append(
            ParamGap(
                step_id=step.step_id,
                tool_name=step.tool_name,
                param_name=param_name,
                label=label,
                description=description,
            )
        )
    return gaps


def build_clarify_message(
    gaps: list[ParamGap],
    *,
    task_summary: str = "",
) -> str:
    if not gaps:
        return ""
    lines: list[str] = []
    prefix = (task_summary or "").strip()
    if prefix:
        lines.append(f"要完成「{prefix}」，还需要以下信息：")
    else:
        lines.append("要完成您的请求，还需要以下信息：")
    seen: set[tuple[str, str]] = set()
    index = 1
    for gap in sorted(gaps, key=lambda g: (g.step_id, g.param_name)):
        key = (gap.param_name, gap.tool_name)
        if key in seen:
            continue
        seen.add(key)
        detail = gap.label
        if gap.description and gap.description != gap.label:
            detail = f"{gap.label}（{gap.description}）"
        lines.append(f"{index}. **{detail}** — 用于 {gap.tool_name}")
        index += 1
    lines.append("\n请补充后我再继续处理。")
    return "\n".join(lines)


def check_plan_readiness(
    plan: ExecutionPlan,
    registry: ToolRegistry,
    *,
    step_filter: set[int] | None = None,
    task_summary: str = "",
) -> PlanReadinessVerdict:
    """Gate B：校验无依赖步骤的 required 参数是否齐全。"""
    all_gaps: list[ParamGap] = []
    for step in plan.steps:
        if step_filter is not None and step.step_id not in step_filter:
            continue
        if not step.tool_name:
            continue
        tool = registry.get(step.tool_name)
        if tool is None:
            continue
        tool_def = {
            "name": tool.name,
            "description": tool.description,
            "parameters": tool.parameters,
        }
        all_gaps.extend(check_step(step, tool_def))

    if not all_gaps:
        return PlanReadinessVerdict(ready=True)

    message = build_clarify_message(all_gaps, task_summary=task_summary)
    return PlanReadinessVerdict(
        ready=False,
        gaps=tuple(all_gaps),
        clarify_message=message,
    )
