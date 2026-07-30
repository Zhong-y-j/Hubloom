"""Typed 动作与控制 tool 定义（§20.7）。"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

from core.models import ToolCall

CONTROL_ASK = "agent_ask"
CONTROL_CONFIRM = "agent_await_confirm"
CONTROL_FINISH = "agent_finish"

CONTROL_TOOL_NAMES = frozenset({CONTROL_ASK, CONTROL_CONFIRM, CONTROL_FINISH})

ActionKind = Literal["act", "ask", "await_confirm", "finish"]


@dataclass
class ActAction:
    kind: Literal["act"] = "act"
    tool_calls: list[ToolCall] = field(default_factory=list)
    content: str = ""
    reasoning_content: str = ""


@dataclass
class AskAction:
    kind: Literal["ask"] = "ask"
    question: str = ""
    slots: list[str] = field(default_factory=list)
    content: str = ""
    reasoning_content: str = ""


@dataclass
class AwaitConfirmAction:
    kind: Literal["await_confirm"] = "await_confirm"
    prompt: str = ""
    payload: dict[str, Any] = field(default_factory=dict)
    content: str = ""
    reasoning_content: str = ""


@dataclass
class FinishAction:
    kind: Literal["finish"] = "finish"
    summary: str = ""
    cites: list[str] = field(default_factory=list)
    content: str = ""
    reasoning_content: str = ""


TypedAction = ActAction | AskAction | AwaitConfirmAction | FinishAction


def control_tool_definitions() -> list[dict[str, Any]]:
    """给 LLM 的控制 tool schema（与业务 tools 一并下发）。"""
    return [
        {
            "name": CONTROL_ASK,
            "description": (
                "向用户追问缺参或澄清（本步不要同时调用业务工具）。"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "question": {
                        "type": "string",
                        "description": "向用户提出的问题（简体中文）",
                    },
                    "slots": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "仍缺的字段名（可选）",
                    },
                },
                "required": ["question"],
            },
        },
        {
            "name": CONTROL_CONFIRM,
            "description": (
                "高风险操作前请求用户确认（本步不要同时调用业务工具）。"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "prompt": {
                        "type": "string",
                        "description": "确认提示（简体中文）",
                    },
                    "payload": {
                        "type": "object",
                        "description": "可选上下文",
                    },
                },
                "required": ["prompt"],
            },
        },
        {
            "name": CONTROL_FINISH,
            "description": (
                "本轮收工：给出面向用户的最终总结（简体中文）。"
                "不再调用业务工具时必须调用本工具（或仅输出纯文本将被收成 finish）。"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "summary": {
                        "type": "string",
                        "description": "给用户的最终说明",
                    },
                    "cites": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "可选证据 id（Evidence Journal）",
                    },
                },
                "required": ["summary"],
            },
        },
    ]


class ActionParseError(ValueError):
    """Decide 输出无法收成合法 Typed 动作。"""


def parse_decide_output(
    *,
    content: str,
    reasoning_content: str,
    tool_calls: list[ToolCall],
) -> TypedAction:
    """将一轮 LLM 输出解析为互斥 Typed 动作。"""
    cleaned = (content or "").strip()
    reasoning = (reasoning_content or "").strip()
    calls = list(tool_calls or [])

    if not calls:
        # §20.7：纯文本收成 finish
        return FinishAction(
            summary=cleaned or "（无输出）",
            content=cleaned,
            reasoning_content=reasoning,
        )

    control = [c for c in calls if c.name in CONTROL_TOOL_NAMES]
    business = [c for c in calls if c.name not in CONTROL_TOOL_NAMES]

    if control and business:
        names = ", ".join(c.name for c in calls)
        raise ActionParseError(
            f"同一步不能同时调用控制工具与业务工具：{names}"
        )

    if len(control) > 1:
        names = ", ".join(c.name for c in control)
        raise ActionParseError(f"同一步只能有一个控制动作：{names}")

    if control:
        c = control[0]
        args = c.arguments if isinstance(c.arguments, dict) else {}
        if c.name == CONTROL_FINISH:
            summary = str(args.get("summary") or cleaned or "").strip()
            cites_raw = args.get("cites") or []
            cites = [str(x) for x in cites_raw] if isinstance(cites_raw, list) else []
            return FinishAction(
                summary=summary or cleaned or "已完成",
                cites=cites,
                content=cleaned,
                reasoning_content=reasoning,
            )
        if c.name == CONTROL_ASK:
            question = str(args.get("question") or cleaned or "").strip()
            slots_raw = args.get("slots") or []
            slots = [str(x) for x in slots_raw] if isinstance(slots_raw, list) else []
            return AskAction(
                question=question or "请补充必要信息。",
                slots=slots,
                content=cleaned,
                reasoning_content=reasoning,
            )
        # CONFIRM
        prompt = str(args.get("prompt") or cleaned or "").strip()
        payload = args.get("payload") if isinstance(args.get("payload"), dict) else {}
        return AwaitConfirmAction(
            prompt=prompt or "请确认是否继续。",
            payload=dict(payload),
            content=cleaned,
            reasoning_content=reasoning,
        )

    return ActAction(
        tool_calls=business,
        content=cleaned,
        reasoning_content=reasoning,
    )
