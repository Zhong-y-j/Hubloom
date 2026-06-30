"""工具参数校验辅助（ReAct / MCP 组参）。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

_DEFERRED_PLACEHOLDER_MARKERS = ("{{", "}}")


@dataclass(frozen=True)
class ParamGap:
    step_id: int
    tool_name: str
    param_name: str
    label: str
    description: str = ""


def is_present(value: Any) -> bool:
    """None / 空字符串视为缺失；0、False、[] 视为已提供。"""
    if value is None:
        return False
    if isinstance(value, str) and value.strip() == "":
        return False
    return True


def is_deferred_arg(value: Any) -> bool:
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


def format_missing_args_message(gaps: list[ParamGap]) -> str:
    """缺参时不调 API，直接返回此说明。"""
    if not gaps:
        return "缺少必填参数"
    parts: list[str] = []
    for gap in gaps:
        detail = gap.label
        if gap.description and gap.description != gap.label:
            detail = f"{gap.label}（{gap.description}）"
        parts.append(f"{detail}（{gap.param_name}）")
    return "缺少必填参数：" + "、".join(parts)
