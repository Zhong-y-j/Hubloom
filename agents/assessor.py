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

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from core.models import Message, Role

if TYPE_CHECKING:
    from core.provider import LLMProvider

ASSESSOR_SYSTEM = """你是智能助手流水线中的路由分类器，判断当前用户消息是否需要进入「深度思考」阶段。

深度思考（need_deep_think=true）适用于：
- 需要调用外部工具或 API 获取、查询、创建、修改、删除业务数据
- 需要检索记忆、知识库或结合多轮上下文才能完成的任务
- 需要多步规划或前后依赖才能完成的操作

直接回复（need_deep_think=false）适用于：
- 寒暄、致谢、告别及一般闲聊
- 询问助手身份、能力范围等产品层问题
- 纯概念讨论、方案探讨、征求看法，且不需要访问外部业务系统或工具

只输出一个 JSON 对象，不要其它文字：
{"need_deep_think": true或false, "reason": "不超过20字"}
"""


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
    def __init__(self, llm: LLMProvider, *, max_tokens: int = 64) -> None:
        self.llm = llm
        self._max_tokens = max_tokens

    async def evaluate(self, task: str) -> AssessResult:
        text = (task or "").strip()
        if not text:
            return AssessResult(need_deep_think=False, reason="输入为空", task=text)

        out = await self.llm.generate(
            messages=[
                Message(role=Role.SYSTEM, content=ASSESSOR_SYSTEM),
                Message(role=Role.USER, content=text),
            ],
            tools=None,
            max_tokens=self._max_tokens,
        )
        data = _extract_json_object(out.content or "")
        return _parse_result(data, task=text)


async def _demo() -> None:
    from core.factory import create_llm

    assessor = Assessor(create_llm())
    samples = (
        "评估器无法 100% 稳，只靠通用 prompt 时，模型仍可能偶发误判。若线上仍经常错，再考虑",
    )

    print("=== Assessor ===\n")
    for q in samples:
        t0 = time.perf_counter()
        result = await assessor.evaluate(q)
        ms = int((time.perf_counter() - t0) * 1000)
        print(f"用户：{q}")
        print(
            f"  need_deep_think={result.need_deep_think}  reason={result.reason!r}  ({ms}ms)\n"
        )


if __name__ == "__main__":
    asyncio.run(_demo())
