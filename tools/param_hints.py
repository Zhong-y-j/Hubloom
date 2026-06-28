"""从 MCP/OpenAPI parameters 提取 ReAct 澄清用的字段提示（无 agents 依赖）。"""

from __future__ import annotations

from typing import Any


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


def _is_optional_param(schema: dict[str, Any]) -> bool:
    desc = str(schema.get("description") or "")
    if "可选" in desc or "optional" in desc.lower():
        return True
    return bool(schema.get("nullable"))


def params_for_user_clarification(
    parameters: dict[str, Any],
) -> list[tuple[str, str, str]]:
    """ReAct 澄清用：列出需向用户收集的参数（param_name, label, description）。"""
    if not isinstance(parameters, dict):
        return []
    props = parameters.get("properties") or {}
    if not isinstance(props, dict):
        return []
    required = parameters.get("required") or []
    if not isinstance(required, list):
        required = []
    required_set = {k for k in required if isinstance(k, str)}
    out: list[tuple[str, str, str]] = []
    for param_name, schema in props.items():
        if not isinstance(param_name, str) or not isinstance(schema, dict):
            continue
        if param_name in required_set:
            label, description = describe_param(parameters, param_name)
            out.append((param_name, label, description))
            continue
        if required_set:
            continue
        if _is_optional_param(schema):
            continue
        label, description = describe_param(parameters, param_name)
        out.append((param_name, label, description))
    return out


def format_tool_param_hints(parameters: dict[str, Any]) -> str:
    """将工具 parameters 压缩为一行「需用户提供」说明。"""
    params = params_for_user_clarification(parameters)
    if not params:
        return ""
    parts: list[str] = []
    for _param_name, label, description in params:
        detail = label
        if description and description != label:
            detail = f"{label}（{description}）"
        parts.append(detail)
    return "、".join(parts)
