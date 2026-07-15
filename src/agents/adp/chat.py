"""ADP 快答路径（Chat）：单轮流式直答，不走 Thought / 工具执行。

编排层先用 ``ContextAssembler.assemble`` 拼好 ``list[Message]``，再传入 ``Chat.run_stream``。
本模块只负责调用 LLM 并产出最终结果区事件；SYSTEM 等不落库，由编排层每轮重新装配。
"""

from __future__ import annotations

import sys
from collections.abc import AsyncIterator
from pathlib import Path
from typing import TYPE_CHECKING

_ROOT = Path(__file__).resolve().parents[2]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from core.models import Message, TokenUsage
from core.provider import DeltaEvent, StreamEndEvent, StreamErrorEvent

from agents.events import (
    AgentEvent,
    ErrorEvent,
    FinalAnswerDeltaEvent,
    FinalAnswerEvent,
)
from agents.agent_log import clip, cortex_log
from agents.adp.thought import format_tool_summaries
from memory.context import ContextAssembler
from tools.registry import ToolRegistry

if TYPE_CHECKING:
    from core.provider import LLMProvider

_CHAT_SYSTEM = """你是 **Hubloom**，面向用户的智能助手。

要求：
- 语气自然、专业、可执行
- 结合对话历史作答
- 自我介绍或能力介绍时：根据下方「可用工具」与「API 分组」各条 description 归纳 2～5 条用户可发起的任务示例
- 禁止编造未出现在工具列表中的能力或服务
- 本路径不调用外部工具；若用户需要查询或修改业务数据，友好说明可以协助，并引导其说出具体需求
- 不要提及内部架构、评估器、快慢路径、ReAct 等术语
"""


def build_chat_system_prompt(
    tools: ToolRegistry | None,
    base: str | None = None,
    *,
    catalog_snippet: str = "",
) -> str:
    """快答 system prompt（含 API 分组目录与工具能力简表），供编排层 ``assemble`` 使用。"""
    parts = [(base or _CHAT_SYSTEM).strip()]
    snippet = (catalog_snippet or "").strip()
    if snippet:
        parts.append(snippet)
    if tools is not None:
        summary = format_tool_summaries(tools)
        if summary:
            parts.append(summary)
    return "\n\n".join(parts)


def assemble_chat_messages(
    task: str,
    *,
    tools: ToolRegistry | None = None,
    system_prompt: str | None = None,
    histories: list[Message] | None = None,
    assembler: ContextAssembler | None = None,
) -> list[Message]:
    """编排层辅助：与旧 ReAct bootstrap 相同结构，暂不接 memories / documents / graph。"""
    return (assembler or ContextAssembler()).assemble(
        system_prompt=build_chat_system_prompt(tools, system_prompt),
        histories=histories,
        current_task=(task or "").strip(),
    )


class Chat:
    """快答路径：消费已装配的 ``messages``，流式直答，不调工具。"""

    def __init__(self, llm: LLMProvider) -> None:
        self.llm = llm

    async def run_stream(
        self,
        messages: list[Message],
    ) -> AsyncIterator[AgentEvent]:
        """流式直答。``messages`` 由编排层 ``ContextAssembler.assemble`` 产出。"""
        if not messages:
            yield FinalAnswerEvent(content="未收到有效消息，请重新输入。")
            return

        cortex_log("chat run_stream start", message_count=len(messages))
        full_text = ""
        usage: TokenUsage | None = None

        async for ev in self.llm.generate_stream(messages=messages, tools=None):
            if isinstance(ev, DeltaEvent):
                if ev.delta:
                    full_text += ev.delta
                    yield FinalAnswerDeltaEvent(delta=ev.delta)
            elif isinstance(ev, StreamEndEvent):
                usage = ev.output.usage
                break
            elif isinstance(ev, StreamErrorEvent):
                cortex_log(
                    "chat stream error",
                    error=clip(str(ev.error), 120),
                )
                yield ErrorEvent(error=str(ev.error))
                return
        else:
            cortex_log("chat stream incomplete", reason="no StreamEndEvent")
            yield ErrorEvent(error="LLM 流结束但未收到 StreamEndEvent")
            return

        answer = full_text.strip()
        if not answer:
            cortex_log("chat empty answer")
            yield ErrorEvent(error="未能生成回复")
            return

        cortex_log(
            "chat run_stream done",
            answer_len=len(answer),
            prompt_tokens=getattr(usage, "prompt_tokens", None) if usage else None,
            completion_tokens=getattr(usage, "completion_tokens", None) if usage else None,
        )
        yield FinalAnswerEvent(content=answer, usage=usage)


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
        chat = Chat(create_llm())
        query = "你有什么能力呢"

        # 编排层：装配 messages（与 agents copy/react/agent.py bootstrap 同结构）
        messages = assemble_chat_messages(
            query,
            tools=tools,
            histories=[],
        )

        print(f"已加载 {len(tools.list_definitions())} 个工具\n")
        print(f"--- 用户：{query} ---\n")
        print("【最终回复】")
        async for ev in chat.run_stream(messages):
            if isinstance(ev, FinalAnswerDeltaEvent):
                print(ev.delta, end="", flush=True)
            elif isinstance(ev, FinalAnswerEvent):
                if ev.content:
                    print()
            elif isinstance(ev, ErrorEvent):
                print(f"\n[错误] {ev.error}")
        print()
    finally:
        await bindings.client.close()


if __name__ == "__main__":
    import asyncio

    from observability import setup_log

    setup_log()
    asyncio.run(main())
