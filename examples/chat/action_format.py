"""将结构化 ChatAction 译为 Agent 触发文案（非用户闲聊）。"""

from __future__ import annotations

from examples.chat.schemas import ChatAction


def format_action_trigger(action: ChatAction) -> str:
    """供 Runtime 消费的触发正文；保留 ``[A2UI:name]`` 行以兼容既有习惯。"""
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
    return "\n".join(lines)
