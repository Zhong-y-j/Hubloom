"""LLM 调用前上下文落盘：Think / Respond 的完整 messages（及 Think 的 tools）。

写入 ``logs/llm_context.log``（与 debug.log 分离，避免巨量 system/tools 冲刷主日志）。
每次调用前追加一条可读分隔记录 + JSON，便于对照复现请求。
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from core.models import Message

_DEFAULT_PATH = Path("logs/llm_context.log")


def _message_to_dict(msg: Message) -> dict[str, Any]:
    """与 OpenAI 兼容请求体对齐的完整序列化（不截断）。"""
    row: dict[str, Any] = {
        "role": msg.role.value if hasattr(msg.role, "value") else str(msg.role),
        "content": msg.content,
    }
    if msg.tool_calls:
        row["tool_calls"] = [
            {
                "id": tc.id,
                "type": "function",
                "function": {
                    "name": tc.name,
                    "arguments": tc.arguments,
                },
            }
            for tc in msg.tool_calls
        ]
    if msg.tool_call_id:
        row["tool_call_id"] = msg.tool_call_id
    if msg.name:
        row["name"] = msg.name
    return row


def dump_llm_context(
    *,
    phase: str,
    messages: list[Message],
    round_i: int | None = None,
    present_mode: str | None = None,
    tools: list[dict[str, Any]] | None = None,
    path: Path | str | None = None,
) -> Path:
    """在 LLM 执行前把完整上下文追加到日志文件。

    Parameters
    ----------
    phase:
        ``think`` / ``respond``（或其它调用方自定义标签）。
    messages:
        即将交给模型的完整 messages。
    tools:
        Think 阶段传入的工具定义；Respond 一般为 ``None``。
    """
    out = Path(path or _DEFAULT_PATH)
    out.parent.mkdir(parents=True, exist_ok=True)

    ts = datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")
    payload: dict[str, Any] = {
        "ts": ts,
        "phase": phase,
        "message_count": len(messages),
        "messages": [_message_to_dict(m) for m in messages],
    }
    if round_i is not None:
        payload["round"] = round_i
    if present_mode is not None:
        payload["present_mode"] = present_mode
    if tools is not None:
        payload["tool_count"] = len(tools)
        payload["tools"] = tools

    label = phase
    if round_i is not None:
        label = f"{phase}#{round_i}"
    if present_mode:
        label = f"{label} mode={present_mode}"

    block = (
        f"\n{'=' * 72}\n"
        f"{ts} | LLM context | {label} | messages={len(messages)}"
        + (f" | tools={len(tools)}" if tools is not None else "")
        + f"\n{'=' * 72}\n"
        f"{json.dumps(payload, ensure_ascii=False, indent=2)}\n"
    )
    with out.open("a", encoding="utf-8") as f:
        f.write(block)
    return out.resolve()
