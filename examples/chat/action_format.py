"""将结构化 ChatAction 译为 AG-UI 风格的 tool 消息对（进 Runtime）。"""

from __future__ import annotations

import json
from typing import Any

from core.models import Message, Role, ToolCall

from agent.turn_state import A2UI_ACTION_TOOL_NAME
from examples.chat.schemas import ChatAction

__all__ = [
    "A2UI_ACTION_TOOL_NAME",
    "action_to_tool_messages",
    "format_action_display",
    "format_action_trigger",
]


def format_action_trigger(action: ChatAction) -> str:
    """tool 回传正文；保留 ``[A2UI:name]`` 行以兼容既有习惯。"""
    name = (action.name or "").strip() or "unknown"
    kind = action.type
    header = f"【人机动作 · {kind} · 非用户闲聊】"
    lines = [header, f"[A2UI:{name}]"]

    if kind == "cancel":
        lines.append("(用户取消当前表单)")
        lines.append(
            "说明: 请确认已取消；不要再次弹出同一表单，除非用户另有请求。"
        )
        return "\n".join(lines)

    payload = action.payload or {}
    if payload:
        for key, value in payload.items():
            if value is None:
                continue
            if isinstance(value, str) and not value.strip():
                continue
            if isinstance(value, (str, int, float, bool)):
                text = str(value)
            else:
                text = repr(value)
            lines.append(f"{key}: {text}")
    else:
        lines.append("(无额外字段)")

    if action.surface_id:
        lines.append(f"surface_id: {action.surface_id}")
    if action.source_component_id:
        lines.append(f"source_component_id: {action.source_component_id}")

    # 给 Think 的硬约束：避免「误触发」叙事与 Respond 另造列表
    lower = name.lower()
    lines.append(
        "说明: 以上为用户真实提交的字段，必须采信；禁止当作误触发或忽略 payload。"
    )
    if any(k in lower for k in ("delete", "remove")) or "删除" in name:
        lines.append(
            "说明: 若为删除/移除确认，payload 中的目标 ID 即为已确认对象；"
            "应据此 call_api，不要再编造其它候选项列表。"
        )
    return "\n".join(lines)


def format_action_display(action: ChatAction) -> str:
    """历史/气泡摘要（非闲聊意图）。"""
    name = (action.name or "").strip() or "unknown"
    if action.type == "cancel":
        return f"已取消表单（{name}）"
    lines = [f"已提交表单：{name}"]
    for key, value in (action.payload or {}).items():
        if value is None:
            continue
        if isinstance(value, str) and not value.strip():
            continue
        if isinstance(value, (str, int, float, bool)):
            text = str(value)
        else:
            text = json.dumps(value, ensure_ascii=False)
        lines.append(f"{key}: {text}")
    return "\n".join(lines)


def action_to_tool_messages(
    action: ChatAction,
    *,
    tool_call_id: str,
    source_run_id: str | None = None,
) -> list[Message]:
    """译为 ``assistant(tool_calls) + tool``，对齐 AG-UI ``role: tool`` + ``toolCallId``。"""
    tid = (tool_call_id or "").strip()
    if not tid:
        raise ValueError("tool_call_id 不能为空")
    name = (action.name or "").strip() or "unknown"
    args: dict[str, Any] = {
        "type": action.type,
        "name": name,
    }
    if source_run_id:
        args["source_run_id"] = source_run_id
    stub = Message(
        role=Role.ASSISTANT,
        content="",
        tool_calls=[
            ToolCall(
                id=tid,
                name=A2UI_ACTION_TOOL_NAME,
                arguments=args,
            )
        ],
    )
    tool = Message(
        role=Role.TOOL,
        content=format_action_trigger(action),
        tool_call_id=tid,
        name=A2UI_ACTION_TOOL_NAME,
    )
    return [stub, tool]
