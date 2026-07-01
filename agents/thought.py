"""ADP 深度思考路径（Thought）：编排 研判 → 执行 → 总结 → 响应。

对外事件分两块：
- **思考过程区**：``deliberate`` / ``execute`` / ``replan`` 的文本，以及工具调用事件
- **最终结果区**：仅 ``respond`` 产出的 ``FinalAnswerDeltaEvent`` / ``FinalAnswerEvent``
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

from core.models import Message, Role, StopReason, TokenUsage
from core.provider import DeltaEvent, StreamEndEvent, StreamErrorEvent

from agents.events import (
    AgentEvent,
    ErrorEvent,
    FinalAnswerDeltaEvent,
    FinalAnswerEvent,
    ThoughtDeltaEvent,
    ToolCallEvent,
    ToolResultEvent,
)
from tools.registry import ToolRegistry
from tools.runner import ToolRunner

if TYPE_CHECKING:
    from core.provider import LLMProvider

_DELIBERATE_BEFORE = """你是 Agent Cortex（灵枢），正在心里盘算接下来如何处理用户任务，并把思路说出来。

身份与语气：
- 以第一人称「我」叙述，简洁、干脆，一两句话说完
- 像在跟用户简要交流

结合「可用工具」判断：
- 列表里有对得上的工具：说明我将如何用（先…再…），可引用工具名
- 仅有名称、没有 ID 且存在列表类工具：应先查列表再查详情
- 列表里根本没有相关工具：直接说明「当前没有…相关能力，暂时无法完成」，不要绕弯追问
- 有工具但缺用户必填信息：简短说「我会向您确认…」即可，**不要**列出具体字段或替用户填表

禁止：直接回答业务结果、问候用户、分条列表、JSON、编造不存在的工具、在研判阶段向用户追问具体参数。
"""

_DELIBERATE_REPLAN = """你是 Agent Cortex（灵枢）。先前执行遇到问题，请简要说明你将如何调整后续处理思路。

要求：一两句第一人称中文；只讲调整方向，不重复最终业务答案；可引用可用工具名。
"""

_DELIBERATE_AFTER = """你是 Agent Cortex（灵枢）。工具执行已结束，请简要总结刚才的处理情况。

要求：一两句第一人称中文；概括做了什么、结果如何；这是过程小结，不是给用户的最终正式答复。
"""

_EXECUTE = """你是 Agent Cortex（灵枢）的执行阶段。根据任务调用可用工具获取真实数据。

要求：
- 优先调用工具，不要编造业务数据
- 调用前后最多一句简短进度（如「正在查询小区列表」），不要展开说明
- 缺必填参数时，用一两句中文向用户追问（此时勿调用工具）
- 所需数据已查齐后停止调用工具即可，**不要**整理成 Markdown 报告、表格或给用户看的完整结论
- 禁止提及「执行层」「ReAct」等内部术语
"""

_RESPOND = """你是 Agent Cortex（灵枢），面向用户的智能助手。请根据用户任务与已执行的工具结果，给出最终正式回复。

要求：
- 语气自然、专业，直接回答用户问题
- 仅依据工具返回的真实数据作答，不要编造
- 数据不足时如实说明，并告知用户还需什么信息
- 不要提及内部流程、研判、执行层等术语
- 不要重复过程性小结，直接给结论或完整答复
"""


class ThoughtPhase(str, Enum):
    """思考阶段（均归入思考过程区事件）。"""

    BEFORE_EXECUTE = "before_execute"
    EXECUTE = "execute"
    REPLAN = "replan"
    AFTER_EXECUTE = "after_execute"


def format_tool_summaries(tools: ToolRegistry) -> str:
    """工具简表（名称 + 描述）。"""
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


def build_deliberate_prompt(tools: ToolRegistry | None, phase: ThoughtPhase) -> str:
    """按阶段组装研判用 system prompt。"""
    base = {
        ThoughtPhase.BEFORE_EXECUTE: _DELIBERATE_BEFORE,
        ThoughtPhase.REPLAN: _DELIBERATE_REPLAN,
        ThoughtPhase.AFTER_EXECUTE: _DELIBERATE_AFTER,
    }[phase]
    parts = [base.strip()]
    if tools is not None:
        summary = format_tool_summaries(tools)
        if summary:
            parts.append(summary)
    return "\n\n".join(parts)


def build_execute_prompt(tools: ToolRegistry | None) -> str:
    """组装 ReAct 执行用 system prompt。"""
    parts = [_EXECUTE.strip()]
    if tools is not None:
        summary = format_tool_summaries(tools)
        if summary:
            parts.append(summary)
    return "\n\n".join(parts)


def _execute_user_message(task: str, observations: list[str]) -> str:
    text = (task or "").strip()
    if not observations:
        return text
    obs_block = "\n".join(observations)
    return f"任务：\n{text}\n\n已执行观察：\n{obs_block}"


def _respond_user_message(task: str, observations: list[str]) -> str:
    text = (task or "").strip()
    obs_part = ""
    if observations:
        obs_part = "\n\n执行观察：\n" + "\n".join(observations)
    return f"用户任务：\n{text}{obs_part}\n\n请给出最终正式回复。"


def _respond_messages(
    task: str, execute_messages: list[Message], observations: list[str]
) -> list[Message]:
    """组装响应阶段消息：优先复用执行轮对话，否则回退到任务 + 观察。"""
    if execute_messages:
        return [
            Message(role=Role.SYSTEM, content=_RESPOND.strip()),
            *execute_messages[1:],
            Message(role=Role.USER, content="请根据以上内容，向用户给出最终正式回复。"),
        ]
    return [
        Message(role=Role.SYSTEM, content=_RESPOND.strip()),
        Message(role=Role.USER, content=_respond_user_message(task, observations)),
    ]


def _deliberate_user_message(
    task: str,
    phase: ThoughtPhase,
    observations: list[str],
) -> str:
    text = task.strip()
    obs_block = ""
    if observations:
        obs_block = "执行观察：\n" + "\n".join(observations)

    if phase == ThoughtPhase.BEFORE_EXECUTE:
        return f"请说明你（Agent Cortex）打算如何处理该任务：\n{text}"

    if phase == ThoughtPhase.REPLAN:
        body = f"请说明你将如何调整处理方案：\n{text}"
        return f"{body}\n\n{obs_block}" if obs_block else body

    body = f"请总结刚才的执行情况：\n{text}"
    return f"{body}\n\n{obs_block}" if obs_block else body


class Thought:
    """深度路径：内部循环 研判 → 执行 →（可选重规划）→ 总结 → 响应。"""

    def __init__(
        self,
        llm: LLMProvider,
        tools: ToolRegistry | None = None,
        *,
        max_execute_steps: int = 20,
        max_replan_rounds: int = 2,
    ) -> None:
        self.llm = llm
        self.tools = tools
        self.max_execute_steps = max_execute_steps
        self.max_replan_rounds = max_replan_rounds
        self._observations: list[str] = []
        self._execute_messages: list[Message] = []
        self._execute_had_errors = False
        self._execute_hit_step_limit = False

    # ------------------------------------------------------------------
    # 主流程
    # ------------------------------------------------------------------

    async def run_stream(self, task: str) -> AsyncIterator[AgentEvent]:
        """深度路径入口：组合各阶段。"""
        async for ev in self.deliberate(task, ThoughtPhase.BEFORE_EXECUTE):
            yield ev

        async for ev in self.execute(task):
            yield ev

        replan_round = 0
        while self.should_replan(task) and replan_round < self.max_replan_rounds:
            replan_round += 1
            async for ev in self.replan(task):
                yield ev
            async for ev in self.execute(task, resume=True):
                yield ev

        async for ev in self.deliberate(task, ThoughtPhase.AFTER_EXECUTE):
            yield ev

        async for ev in self.respond(task):
            yield ev

    # ------------------------------------------------------------------
    # 阶段方法
    # ------------------------------------------------------------------

    async def deliberate(
        self,
        task: str,
        phase: ThoughtPhase,
    ) -> AsyncIterator[AgentEvent]:
        """流式研判：规划 / 重规划说明 / 执行后总结。"""
        text = (task or "").strip()
        if not text:
            yield ThoughtDeltaEvent(
                phase=phase.value,
                delta="未收到有效任务，暂无处理思路。",
            )
            return

        system = build_deliberate_prompt(self.tools, phase)
        user_content = _deliberate_user_message(text, phase, self._observations)

        async for ev in self.llm.generate_stream(
            messages=[
                Message(role=Role.SYSTEM, content=system),
                Message(role=Role.USER, content=user_content),
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

    async def execute(
        self, task: str, *, resume: bool = False
    ) -> AsyncIterator[AgentEvent]:
        """ReAct 执行环：调工具、追问用户、观察结果。"""
        text = (task or "").strip()
        if not text:
            return

        if self.tools is None or not self.tools.list_definitions():
            yield ErrorEvent(error="未配置可用工具，无法执行")
            return

        self._execute_had_errors = False
        self._execute_hit_step_limit = False
        tool_defs = self.tools.list_definitions()
        tool_runner = ToolRunner(self.tools)

        if resume and self._execute_messages:
            self._execute_messages[0] = Message(
                role=Role.SYSTEM, content=build_execute_prompt(self.tools)
            )
            self._execute_messages.append(
                Message(
                    role=Role.USER,
                    content=(
                        "先前执行未完全完成或遇到问题。请根据已有工具结果继续完成剩余任务，"
                        "优先补齐未完成的查询。"
                    ),
                )
            )
        else:
            self._execute_messages = [
                Message(role=Role.SYSTEM, content=build_execute_prompt(self.tools)),
                Message(
                    role=Role.USER,
                    content=_execute_user_message(text, self._observations),
                ),
            ]

        for _ in range(self.max_execute_steps):
            full_text = ""
            final_stop: StopReason | None = None
            tool_calls = []

            async for ev in self.llm.generate_stream(
                messages=self._execute_messages,
                tools=tool_defs,
            ):
                if isinstance(ev, DeltaEvent):
                    full_text += ev.delta
                    if ev.delta:
                        yield ThoughtDeltaEvent(
                            phase=ThoughtPhase.EXECUTE.value,
                            delta=ev.delta,
                        )
                elif isinstance(ev, StreamEndEvent):
                    out = ev.output
                    final_stop = out.stop_reason
                    tool_calls = out.tool_calls
                    break
                elif isinstance(ev, StreamErrorEvent):
                    yield ErrorEvent(error=str(ev.error))
                    return

            if final_stop is None:
                yield ErrorEvent(error="LLM 流结束但未收到 StreamEndEvent")
                return

            if final_stop == StopReason.STOP:
                answer = full_text.strip()
                if answer:
                    self._execute_messages.append(
                        Message(role=Role.ASSISTANT, content=answer)
                    )
                self._execute_hit_step_limit = False
                return

            if final_stop == StopReason.TOOL_CALLS and tool_calls:
                self._execute_messages.append(
                    Message(
                        role=Role.ASSISTANT,
                        content=full_text.strip(),
                        tool_calls=tool_calls,
                    )
                )

                for tc in tool_calls:
                    yield ToolCallEvent(
                        call_id=tc.id,
                        tool_name=tc.name,
                        args=tc.arguments,
                    )

                results = await asyncio.gather(
                    *[tool_runner.run(tc.name, tc.arguments) for tc in tool_calls]
                )

                for tc, (result, is_error) in zip(tool_calls, results):
                    if is_error:
                        self._execute_had_errors = True
                    yield ToolResultEvent(
                        call_id=tc.id,
                        tool_name=tc.name,
                        result=result,
                        is_error=is_error,
                    )
                    self.append_tool_result(tc.name, result, is_error=is_error)
                    self._execute_messages.append(
                        Message(
                            role=Role.TOOL,
                            content=result,
                            tool_call_id=tc.id,
                            name=tc.name,
                        )
                    )
                continue

            if final_stop == StopReason.LENGTH:
                yield ErrorEvent(error="生成长度超限，执行中断")
                return

            yield ErrorEvent(error=f"未处理的结束原因：{final_stop}")
            return

        self._execute_hit_step_limit = True
        yield ErrorEvent(error=f"执行步数已达上限（{self.max_execute_steps}）")

    async def replan(self, task: str) -> AsyncIterator[AgentEvent]:
        """工具失败或计划失效时，重新研判后续步骤。"""
        async for ev in self.deliberate(task, ThoughtPhase.REPLAN):
            yield ev

    async def respond(self, task: str) -> AsyncIterator[AgentEvent]:
        """基于执行结果生成最终用户可见回复。"""
        text = (task or "").strip()
        if not text:
            yield FinalAnswerEvent(content="未收到有效任务，请重新描述您的需求。")
            return

        messages = _respond_messages(text, self._execute_messages, self._observations)
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
                yield ErrorEvent(error=str(ev.error))
                return
        else:
            yield ErrorEvent(error="LLM 流结束但未收到 StreamEndEvent")
            return

        answer = full_text.strip()
        if not answer:
            yield ErrorEvent(error="未能生成最终回复")
            return

        yield FinalAnswerEvent(content=answer, usage=usage)

    # ------------------------------------------------------------------
    # 判断与辅助
    # ------------------------------------------------------------------

    def should_replan(self, task: str) -> bool:
        """是否应进入重规划：工具失败，或执行未正常结束（如步数上限）。"""
        if not (task or "").strip():
            return False
        return self._execute_had_errors or self._execute_hit_step_limit

    def append_tool_result(
        self, tool_name: str, result: str, *, is_error: bool
    ) -> None:
        """记录工具观察，供后续研判 / 执行使用。"""
        status = "失败" if is_error else "成功"
        preview = (result or "").strip()
        if len(preview) > 200:
            preview = preview[:197] + "..."
        self._observations.append(f"- {tool_name}（{status}）：{preview}")


async def main():
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
        # query = "帮我列出当前所有小区，并且每个小区的详情，小区绑定的优惠卷，以及这些小区关联的钥匙柜，钥匙柜的状态是什么"
        query = "你有什么能力呢"
        print(f"已加载 {len(tools.list_definitions())} 个工具\n")
        print(f"--- 用户：{query} ---\n")
        thought_phase: str | None = None
        thinking_open = False
        final_open = False
        final_streamed = False

        def _open_thinking() -> None:
            nonlocal thinking_open
            if not thinking_open:
                print("【思考过程】")
                thinking_open = True

        def _open_final() -> None:
            nonlocal final_open, thought_phase
            if not final_open:
                if thinking_open:
                    print()
                print("\n【最终回复】")
                final_open = True
                thought_phase = None

        async for ev in thought.run_stream(query):
            if isinstance(ev, ThoughtDeltaEvent):
                _open_thinking()
                if ev.phase != thought_phase:
                    if thought_phase is not None:
                        print()
                    thought_phase = ev.phase
                print(ev.delta, end="", flush=True)
            elif isinstance(ev, ToolCallEvent):
                _open_thinking()
                if thought_phase is not None:
                    print()
                    thought_phase = None
                print(f"\n→ 调用 {ev.tool_name} {ev.args}")
            elif isinstance(ev, ToolResultEvent):
                tag = "失败" if ev.is_error else "成功"
                preview = (ev.result or "")[:120]
                print(f"\n← {ev.tool_name}（{tag}）：{preview}")
            elif isinstance(ev, FinalAnswerDeltaEvent):
                _open_final()
                final_streamed = True
                print(ev.delta, end="", flush=True)
            elif isinstance(ev, FinalAnswerEvent):
                _open_final()
                if not final_streamed and ev.content:
                    print(ev.content)
                elif final_streamed:
                    print()
            elif isinstance(ev, ErrorEvent):
                _open_thinking()
                print(f"\n[错误] {ev.error}")
        print()
    finally:
        await bindings.client.close()


if __name__ == "__main__":
    import asyncio

    from observability import setup_log

    setup_log()
    asyncio.run(main())
