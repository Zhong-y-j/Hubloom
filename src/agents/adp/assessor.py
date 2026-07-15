"""ADP 评估器：静默、快速路由，判断是否需要进入深度思考层。

仅 LLM + 通用提示词，非流式 JSON 输出，不对用户展示。
"""

from __future__ import annotations

import asyncio
import json
import re
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

_ROOT = Path(__file__).resolve().parents[2]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from core.models import Message, Role

from agents.agent_log import clip, cortex_log

if TYPE_CHECKING:
    from core.provider import LLMProvider


@dataclass(frozen=True)
class AssessResult:
    need_deep_think: bool
    reason: str
    task: str


def _extract_json_object(text: str) -> dict[str, Any]:
    raw = (text or "").strip()
    if not raw:
        raise ValueError("LLM 返回为空")

    fence = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", raw, re.DOTALL)
    if fence:
        raw = fence.group(1)

    start, end = raw.find("{"), raw.rfind("}")
    if start == -1 or end == -1:
        raise ValueError(f"未找到 JSON: {raw[:120]}")

    return json.loads(raw[start : end + 1])


def _parse_result(data: dict[str, Any], task: str) -> AssessResult:
    need = bool(data.get("need_deep_think", True))
    reason = str(data.get("reason", "")).strip() or "（未说明）"
    return AssessResult(need_deep_think=need, reason=reason, task=task)


class Assessor:
    def __init__(self, llm: LLMProvider) -> None:
        self.llm = llm

    async def evaluate(self, messages: list[Message], task: str) -> AssessResult:
        cortex_log(
            "assessor evaluate start",
            task=clip(task, 80),
            history_msgs=max(0, len(messages) - 2),
        )
        try:
            out = await self.llm.generate(
                messages=messages,
                tools=None,
            )
            data = _extract_json_object(out.content or "")
            result = _parse_result(data, task=task)
        except Exception as exc:
            cortex_log(
                "assessor evaluate failed",
                task=clip(task, 80),
                error=type(exc).__name__,
                detail=clip(str(exc), 120),
            )
            raise
        cortex_log(
            "assessor evaluate done",
            task=clip(task, 80),
            need_deep_think=result.need_deep_think,
            reason=clip(result.reason, 40),
            route="thought" if result.need_deep_think else "chat",
        )
        return result
