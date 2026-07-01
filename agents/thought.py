"""ADP 深度思考层（Thought）：结合用户任务与工具能力，流式产出执行研判。

当前接入：LLM + 工具简表（名称 + 描述）。记忆、历史等待后续扩展。
"""

from __future__ import annotations

import asyncio
import sys
from collections.abc import AsyncIterator
from enum import Enum
from pathlib import Path
from typing import TYPE_CHECKING

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from core.models import Message, Role
from core.provider import DeltaEvent, StreamEndEvent, StreamErrorEvent

from agents.events import AgentEvent, ErrorEvent, ThoughtDeltaEvent
from tools.registry import ToolRegistry

if TYPE_CHECKING:
    from core.provider import LLMProvider

THOUGHT_SYSTEM = """你是 Agent Cortex（灵枢），正在心里盘算接下来如何处理用户任务，并把思路说出来。

身份与语气：
- 以第一人称「我」叙述，简洁、干脆，一两句话说完
- 像在跟用户简要交流

结合「可用工具」判断：
- 列表里有对得上的工具：说明我将如何用（先…再…），可引用工具名
- 仅有名称、没有 ID 且存在列表类工具：应先查列表再查详情
- **列表里根本没有相关工具：直接说明「当前没有…相关能力，暂时无法完成」；不要追问用户属于哪个模块、是不是别的资源类型，不要绕弯子**
- 有工具但缺用户必填信息：简短说「我会向您确认…」即可

禁止：
- 直接回答业务结果、问候用户、分条列表、JSON
- 编造不存在的工具
- 在无能为力时仍让用户「进一步说明」「确认是否指其他类型资源」等推脱式追问
"""


def format_tool_summaries(tools: ToolRegistry) -> str:
    """将工具注册表格式化为思考层用的简表（不含 parameters schema）。"""
    defs = tools.list_definitions()
    if not defs:
        return ""

    lines = ["可用工具："]
    for d in defs:
        name = str(d.get("name", "")).strip()
        if not name:
            continue
        desc = str(d.get("description", "")).strip()
        lines.append(f"- {name}：{desc}" if desc else f"- {name}")
    return "\n".join(lines)


def _build_system_prompt(base: str, tools: ToolRegistry | None) -> str:
    parts = [base.strip()]
    if tools is not None:
        summary = format_tool_summaries(tools)
        if summary:
            parts.append(summary)
    return "\n\n".join(parts)


class ThoughtPhase(str, Enum):
    """思考阶段（预留，最小实现暂未区分 prompt）。"""

    BEFORE_EXECUTE = "before_execute"
    AFTER_EXECUTE = "after_execute"
    REPLAN = "replan"


class Thought:
    """深度思考层：流式产出研判文本。"""

    def __init__(
        self,
        llm: LLMProvider,
        tools: ToolRegistry | None = None,
        *,
        system_prompt: str | None = None,
    ) -> None:
        self.llm = llm
        self.tools = tools
        self._system_prompt = _build_system_prompt(
            system_prompt or THOUGHT_SYSTEM,
            tools,
        )

    async def run_stream(
        self,
        task: str,
        *,
        phase: ThoughtPhase = ThoughtPhase.BEFORE_EXECUTE,
    ) -> AsyncIterator[AgentEvent]:
        text = (task or "").strip()
        if not text:
            yield ThoughtDeltaEvent(
                phase=phase.value,
                delta="未收到有效任务，暂无处理思路。",
            )
            return

        async for ev in self.llm.generate_stream(
            messages=[
                Message(role=Role.SYSTEM, content=self._system_prompt),
                Message(
                    role=Role.USER,
                    content=f"请说明你（Agent Cortex）打算如何处理该任务：\n{text}",
                ),
            ],
            tools=None,
        ):
            if isinstance(ev, DeltaEvent):
                yield ThoughtDeltaEvent(phase=phase.value, delta=ev.delta)
            elif isinstance(ev, StreamErrorEvent):
                yield ErrorEvent(error=str(ev.error))
                return
            elif isinstance(ev, StreamEndEvent):
                return

        yield ErrorEvent(error="LLM 流结束但未收到 StreamEndEvent")


async def main() -> None:
    from core.factory import create_llm
    from mcp_adapter import load_mcp_tools
    from tools import ToolRegistry

    bindings = await load_mcp_tools(
        command="uv",
        args=["run", "python", "mcp_adapter/server.py"],
        cwd=str(_ROOT),
    )
    try:
        tools = ToolRegistry.from_tools(bindings.tools)
        thought = Thought(create_llm(), tools)
        query = "告诉我小区 A 的详情状态"
        # query = "我需要查询当前有哪些小区，并且每个小区的详情，以及这些小区关联的钥匙柜，钥匙柜的状态，再帮我禁用小区A的状态"
        print(f"已加载 {len(tools.list_definitions())} 个工具\n")
        print(f"--- 用户：{query} ---\n")
        async for ev in thought.run_stream(query):
            if isinstance(ev, ThoughtDeltaEvent):
                print(ev.delta, end="", flush=True)
            elif isinstance(ev, ErrorEvent):
                print(f"\n[错误] {ev.error}")
    finally:
        await bindings.client.close()


if __name__ == "__main__":
    from observability import setup_log

    setup_log()
    asyncio.run(main())
