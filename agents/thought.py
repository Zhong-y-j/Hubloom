"""ADP 深度思考路径（Thought）：编排 研判 → 执行 → 总结 → 响应。

对外事件分两块：
- **思考过程区**：``deliberate`` / ``execute`` / ``replan`` 的文本，以及工具调用事件
- **最终结果区**：仅 ``respond`` 产出的 ``FinalAnswerDeltaEvent`` / ``FinalAnswerEvent``
"""

from __future__ import annotations

import asyncio
import json
import re
import sys
from collections.abc import AsyncIterator, Awaitable, Callable
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
from agents.agent_log import clip, cortex_log
from tools.registry import ToolRegistry
from tools.runner import ToolRunner

if TYPE_CHECKING:
    from core.provider import LLMProvider

PersistMessageFn = Callable[[Message], Awaitable[None]]

_DELIBERATE_BEFORE = """你是 Agent Cortex（灵枢），正在心里盘算接下来如何处理任务，并把思路写成**内部工作笔记**。

文风（必须遵守）：
- 只用第一人称「我」，像在给自己记笔记，**不是**对用户说话
- **禁止**第二人称：不要出现「您」「你」「向你」「对您」「请问」等称呼或面向用户的句式
- 需要提及用户时，用第三人称「用户」或「该任务」，例如：「用户要添加宠物」「该请求缺少 image 字段」
- 缺信息时写：「我缺少…，需在正式回复中向用户确认」，**不要**在笔记里直接向用户发问或列问卷
- 简洁，一两句话；可引用工具名与步骤（先…再…）

结合「可用工具」判断：
- 有匹配工具：说明我打算如何调用
- 仅有名称、没有 ID 且存在列表类工具：应先查列表再查详情
- 无相关工具：写明「当前没有…相关能力，无法完成」
- 有工具但缺必填参数：写明缺什么，停止即可，不要编造参数

禁止：问候、致歉、对用户承诺、分条问卷、JSON、编造工具、直接给出最终业务答复。
"""

_DELIBERATE_REPLAN = """你是 Agent Cortex（灵枢）。先前执行遇到问题，请用**内部工作笔记**简要记录你将如何调整后续步骤。

要求：一两句第一人称中文；只讲调整方向；**禁止**第二人称（您/你）及面向用户的口吻；可引用可用工具名。

若先前失败原因为未登录/身份认证不足：**不要**规划登录、验证码或 token 换取；写明「鉴权不足，应结束执行并由正式回复告知用户」即可。
"""

_DELIBERATE_AFTER = """你是 Agent Cortex（灵枢）。工具执行已结束，请用**内部工作笔记**简要记录刚才做了什么、结果如何。

要求：
- **仅**根据用户消息中的「执行观察」条目概括；观察里没有的内容一律不得写入
- 一两句第一人称中文，客观概括执行与结果（可含关键 ID、状态）
- 这是过程备忘，**不是**给用户的最终答复
- **禁止**第二人称（您/你）、建议用户下一步怎么做、或任何像在回复用户的语气
- **禁止**编造未出现在「执行观察」中的工具名、调用动作或返回值
"""

_EXECUTE = """你是 Agent Cortex（灵枢）的执行阶段。根据**本轮**任务调用可用工具获取真实数据。

要求：
- **必须**通过工具获取业务数据；会话历史中 assistant 曾给出的数字、列表、ID、状态等均**不可**当作事实，只能作语境参考
- 有匹配工具时，优先发起 tool_calls；不要凭历史对话直接给出业务结论
- 若需输出文字，仅限**内部进度备忘**（如「正在查询宠物列表」），用第一人称、勿用「您/你」
- 缺必填参数时：用一句内部笔记说明缺什么（如「缺少 image URL，暂停调用」），**不要**在文中向用户追问；也勿调用工具
- 所需数据已齐后停止调用即可；**不要**整理成给用户看的报告、表格或完整结论
- 禁止提及「执行层」「ReAct」等内部术语

鉴权与登录（必须遵守）：
- **禁止**调用登录、登出、验证码、token 换取等鉴权类工具（工具名含 login、logout、captcha、token 等）
- 你没有用户密码与验证码，**不得**代替用户登录或猜测凭据
- 若任一工具返回未登录/身份认证失败（HTTP 401/403，或 body.msg 含「身份认证」「未登录」「未提供」等），**立即停止**一切后续工具调用
- 停止时用一句内部笔记写明「当前未登录，无法继续查询」，然后结束执行；**不要**尝试 replan 或自行走登录流程
"""

_AUTH_MSG_KEYWORDS = (
    "身份认证",
    "未登录",
    "未提供",
    "请先登录",
    "登录后",
    "unauthorized",
    "unauthenticated",
    "not authenticated",
    "authentication credentials",
    "permission denied",
    "无权限",
    "没有权限",
)

_LOGIN_TOOL_MARKERS = ("login", "logout", "captcha", "token", "oauth")


def is_login_related_tool(tool_name: str) -> bool:
    """工具名是否属于登录/鉴权类（执行阶段应禁止主动调用）。"""
    name = (tool_name or "").lower()
    return any(marker in name for marker in _LOGIN_TOOL_MARKERS)


def is_unauthenticated_tool_result(result: str) -> bool:
    """从工具返回文本判断是否因未登录/鉴权失败。"""
    text = (result or "").strip()
    if not text:
        return False

    if any(keyword in text for keyword in _AUTH_MSG_KEYWORDS):
        return True
    if re.search(r'"http_status"\s*:\s*(401|403)\b', text):
        return True

    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        return False

    status = data.get("http_status")
    if status in (401, 403):
        return True

    for field in ("error", "msg", "message", "detail"):
        value = data.get(field)
        if isinstance(value, str) and any(k in value for k in _AUTH_MSG_KEYWORDS):
            return True

    body = data.get("body")
    if isinstance(body, dict):
        msg = str(body.get("msg") or body.get("message") or body.get("detail") or "")
        code = body.get("code")
        if msg and any(k in msg for k in _AUTH_MSG_KEYWORDS):
            return True
        if code in (401, 403) and msg:
            return True
        if code in (4000, 4001) and msg and any(
            k in msg for k in ("身份认证", "未登录", "未提供", "token", "Token", "认证")
        ):
            return True

    return False

_EXECUTE_TOOL_NUDGE = """【系统提醒】本轮执行尚未调用任何工具。
会话历史里 assistant 的业务数字、列表、ID 均不可当作本轮事实。
请立即调用合适的可用工具获取真实数据。仅当缺少必填参数、确实无法调用工具时，才用一句内部笔记说明缺什么并结束。"""

_MAX_EXECUTE_TOOL_NUDGES = 2

_RESPOND = """你是 Agent Cortex（灵枢），面向用户的智能助手。请根据用户任务与已执行的工具结果，给出最终正式回复。

要求：
- 语气自然、专业，直接回答用户问题
- 仅依据工具返回的真实数据作答，不要编造
- 若无任何工具执行结果，如实说明暂时无法确认相关数据，不要引用历史对话中的业务数字充数
- 数据不足时如实说明，并告知用户还需什么信息
- 不要提及内部流程、研判、执行层等术语
- 不要重复过程性小结，直接给结论或完整答复

若执行观察中出现未登录/身份认证失败：
- 直接说明当前无法查询所需数据，因为接口需要登录或有效访问凭据
- 引导用户先完成系统登录，或由管理员配置 MCP_TOKEN / 前端 Bearer Token
- **禁止**假装已获取受保护数据，**禁止**建议 Agent 自行代为登录
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


def _task_from_messages(messages: list[Message]) -> str:
    """从编排层 messages 末条 USER 提取当前任务。"""
    for m in reversed(messages):
        if m.role == Role.USER:
            return (m.content or "").strip()
    return ""


def _context_backdrop(messages: list[Message]) -> list[Message]:
    """编排层背景：去掉末条 USER（当前任务），保留记忆块与历史对话。"""
    if not messages:
        return []
    if messages[-1].role == Role.USER:
        return list(messages[:-1])
    return list(messages)


def _execute_user_message(task: str, observations: list[str]) -> str:
    text = (task or "").strip()
    header = (
        "【本轮任务 — 必须通过工具获取真实数据，勿引用历史 assistant 中的业务结论】\n"
        f"{text}"
    )
    if not observations:
        return header
    obs_block = "\n".join(observations)
    return f"{header}\n\n本轮已积累的执行观察：\n{obs_block}"


def _respond_user_message(task: str, observations: list[str]) -> str:
    text = (task or "").strip()
    obs_part = ""
    if observations:
        obs_part = "\n\n执行观察：\n" + "\n".join(observations)
    return f"用户任务：\n{text}{obs_part}\n\n请给出最终正式回复。"


def _respond_messages(
    task: str,
    execute_messages: list[Message],
    observations: list[str],
    *,
    backdrop: list[Message] | None = None,
) -> list[Message]:
    """组装响应阶段消息：优先复用执行轮对话，否则回退到背景 + 任务 + 观察。"""
    if not observations:
        return [
            Message(role=Role.SYSTEM, content=_RESPOND.strip()),
            Message(
                role=Role.USER,
                content=(
                    f"用户任务：\n{(task or '').strip()}\n\n"
                    "本轮未能通过工具获取任何执行结果。"
                    "请如实告知用户暂时无法确认相关数据，不要引用历史对话中的业务数字或列表充数。"
                ),
            ),
        ]
    if execute_messages:
        return [
            Message(role=Role.SYSTEM, content=_RESPOND.strip()),
            *execute_messages[1:],
            Message(role=Role.USER, content="请根据以上内容，向用户给出最终正式回复。"),
        ]
    return [
        Message(role=Role.SYSTEM, content=_RESPOND.strip()),
        *(backdrop or []),
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
        return (
            "【内部笔记，勿对用户说话、勿用您/你】"
            f"记录我打算如何处理该任务：\n{text}"
        )

    if phase == ThoughtPhase.REPLAN:
        body = (
            "【内部笔记，勿对用户说话、勿用您/你】"
            f"记录我将如何调整处理方案：\n{text}"
        )
        return f"{body}\n\n{obs_block}" if obs_block else body

    body = (
        "【内部笔记，勿对用户说话、勿用您/你】"
        "仅根据下方「执行观察」客观记录做了什么与结果；"
        "禁止编造未出现在观察中的工具调用或返回值。\n"
        f"用户任务（上下文）：\n{text}"
    )
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
        persist_message: PersistMessageFn | None = None,
    ) -> None:
        self.llm = llm
        self.tools = tools
        self.max_execute_steps = max_execute_steps
        self.max_replan_rounds = max_replan_rounds
        self._persist_message = persist_message
        self._observations: list[str] = []
        self._execute_messages: list[Message] = []
        self._backdrop: list[Message] = []
        self._execute_had_errors = False
        self._execute_hit_step_limit = False
        self._auth_failure_detected = False

    async def _persist_conversation_message(self, message: Message) -> None:
        """将执行期 ASSISTANT(tool_calls) / TOOL 写入会话存储。"""
        if self._persist_message is None:
            return
        await self._persist_message(message)

    # ------------------------------------------------------------------
    # 主流程
    # ------------------------------------------------------------------

    async def run_stream(self, messages: list[Message]) -> AsyncIterator[AgentEvent]:
        """深度路径入口：消费编排层装配的 messages（背景 + 当前 USER）。"""
        self._observations = []
        self._execute_messages = []
        self._execute_had_errors = False
        self._execute_hit_step_limit = False
        self._auth_failure_detected = False
        self._backdrop = _context_backdrop(messages)

        task = _task_from_messages(messages)
        if not task:
            yield FinalAnswerEvent(content="未收到有效任务，请重新描述您的需求。")
            return

        tool_count = (
            len(self.tools.list_definitions()) if self.tools is not None else 0
        )
        cortex_log(
            "thought run_stream start",
            task=clip(task, 80),
            backdrop_msgs=len(self._backdrop),
            tool_count=tool_count,
        )

        async for ev in self.deliberate(task, ThoughtPhase.BEFORE_EXECUTE):
            yield ev

        async for ev in self.execute(task):
            yield ev

        replan_round = 0
        while self.should_replan(task) and replan_round < self.max_replan_rounds:
            replan_round += 1
            cortex_log(
                "thought replan",
                round=replan_round,
                had_errors=self._execute_had_errors,
                hit_step_limit=self._execute_hit_step_limit,
            )
            async for ev in self.replan(task):
                yield ev
            async for ev in self.execute(task, resume=True):
                yield ev

        if not self._observations:
            yield ThoughtDeltaEvent(
                phase=ThoughtPhase.AFTER_EXECUTE.value,
                delta="本轮未获得工具执行结果，无可汇总的观察。",
            )
        else:
            async for ev in self.deliberate(task, ThoughtPhase.AFTER_EXECUTE):
                yield ev

        async for ev in self.respond(task):
            yield ev

        cortex_log(
            "thought run_stream done",
            task=clip(task, 80),
            observations=len(self._observations),
            replan_rounds=replan_round,
            execute_msgs=len(self._execute_messages),
        )

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
        cortex_log("thought deliberate start", phase=phase.value, task=clip(text, 80))

        async for ev in self.llm.generate_stream(
            messages=[
                Message(role=Role.SYSTEM, content=system),
                *self._backdrop,
                Message(role=Role.USER, content=user_content),
            ],
            tools=None,
        ):
            if isinstance(ev, DeltaEvent):
                yield ThoughtDeltaEvent(phase=phase.value, delta=ev.delta)
            elif isinstance(ev, StreamErrorEvent):
                cortex_log(
                    "thought deliberate error",
                    phase=phase.value,
                    error=clip(str(ev.error), 120),
                )
                yield ErrorEvent(error=str(ev.error))
                return
            elif isinstance(ev, StreamEndEvent):
                cortex_log("thought deliberate done", phase=phase.value)
                return

        cortex_log("thought deliberate incomplete", phase=phase.value)
        yield ErrorEvent(error="LLM 流结束但未收到 StreamEndEvent")

    async def execute(
        self, task: str, *, resume: bool = False
    ) -> AsyncIterator[AgentEvent]:
        """ReAct 执行环：调工具、追问用户、观察结果。"""
        text = (task or "").strip()
        if not text:
            return

        if self.tools is None or not self.tools.list_definitions():
            cortex_log("thought execute skipped", reason="no_tools")
            yield ErrorEvent(error="未配置可用工具，无法执行")
            return

        self._execute_had_errors = False
        self._execute_hit_step_limit = False
        self._auth_failure_detected = False
        observations_at_start = len(self._observations)
        execute_nudges = 0
        tool_defs = self.tools.list_definitions()
        tool_runner = ToolRunner(self.tools)
        cortex_log(
            "thought execute start",
            task=clip(text, 80),
            resume=resume,
            tool_count=len(tool_defs),
            max_steps=self.max_execute_steps,
            observations_at_start=observations_at_start,
        )

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
                *self._backdrop,
                Message(
                    role=Role.USER,
                    content=_execute_user_message(text, self._observations),
                ),
            ]

        for step in range(1, self.max_execute_steps + 1):
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
                    cortex_log(
                        "thought execute stream error",
                        step=step,
                        error=clip(str(ev.error), 120),
                    )
                    yield ErrorEvent(error=str(ev.error))
                    return

            if final_stop is None:
                cortex_log("thought execute incomplete", step=step)
                yield ErrorEvent(error="LLM 流结束但未收到 StreamEndEvent")
                return

            if final_stop == StopReason.STOP:
                answer = full_text.strip()
                tools_called_this_pass = (
                    len(self._observations) > observations_at_start
                )
                if (
                    not tools_called_this_pass
                    and execute_nudges < _MAX_EXECUTE_TOOL_NUDGES
                ):
                    execute_nudges += 1
                    if answer:
                        self._execute_messages.append(
                            Message(role=Role.ASSISTANT, content=answer)
                        )
                    self._execute_messages.append(
                        Message(role=Role.USER, content=_EXECUTE_TOOL_NUDGE)
                    )
                    cortex_log(
                        "thought execute nudge",
                        step=step,
                        attempt=execute_nudges,
                        content_len=len(answer),
                    )
                    continue
                if answer:
                    self._execute_messages.append(
                        Message(role=Role.ASSISTANT, content=answer)
                    )
                self._execute_hit_step_limit = False
                cortex_log(
                    "thought execute done",
                    step=step,
                    stop_reason="stop",
                    content_len=len(answer),
                    tools_called_this_pass=tools_called_this_pass,
                    observations=len(self._observations),
                    nudges=execute_nudges,
                )
                return

            if final_stop == StopReason.TOOL_CALLS and tool_calls:
                tool_names = [tc.name for tc in tool_calls]
                if any(is_login_related_tool(name) for name in tool_names):
                    self._auth_failure_detected = True
                    note = "检测到鉴权类工具调用，当前未登录，停止继续执行。"
                    cortex_log(
                        "thought execute auth blocked",
                        step=step,
                        tools=",".join(tool_names),
                        reason="login_tool",
                    )
                    yield ThoughtDeltaEvent(
                        phase=ThoughtPhase.EXECUTE.value,
                        delta=note,
                    )
                    self._observations.append(f"- 系统（鉴权阻断）：{note}")
                    return

                cortex_log(
                    "thought execute tool_calls",
                    step=step,
                    tools=",".join(tool_names),
                    count=len(tool_calls),
                )
                assistant_msg = Message(
                    role=Role.ASSISTANT,
                    content=full_text.strip(),
                    tool_calls=tool_calls,
                )
                self._execute_messages.append(assistant_msg)
                await self._persist_conversation_message(assistant_msg)

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
                    cortex_log(
                        "thought tool result",
                        step=step,
                        tool=tc.name,
                        is_error=is_error,
                        preview=clip(result, 100),
                    )
                    yield ToolResultEvent(
                        call_id=tc.id,
                        tool_name=tc.name,
                        result=result,
                        is_error=is_error,
                    )
                    self.append_tool_result(tc.name, result, is_error=is_error)
                    tool_msg = Message(
                        role=Role.TOOL,
                        content=result,
                        tool_call_id=tc.id,
                        name=tc.name,
                    )
                    self._execute_messages.append(tool_msg)
                    await self._persist_conversation_message(tool_msg)

                if any(is_unauthenticated_tool_result(result) for result, _ in results):
                    self._auth_failure_detected = True
                    note = "检测到未登录或身份认证失败，停止继续调用工具。"
                    cortex_log(
                        "thought execute auth blocked",
                        step=step,
                        reason="auth_result",
                    )
                    yield ThoughtDeltaEvent(
                        phase=ThoughtPhase.EXECUTE.value,
                        delta=note,
                    )
                    self._observations.append(f"- 系统（鉴权阻断）：{note}")
                    return
                continue

            if final_stop == StopReason.LENGTH:
                cortex_log("thought execute length limit", step=step)
                yield ErrorEvent(error="生成长度超限，执行中断")
                return

            cortex_log(
                "thought execute unexpected stop",
                step=step,
                stop_reason=str(final_stop),
            )
            yield ErrorEvent(error=f"未处理的结束原因：{final_stop}")
            return

        self._execute_hit_step_limit = True
        cortex_log(
            "thought execute step limit",
            max_steps=self.max_execute_steps,
            had_errors=self._execute_had_errors,
        )
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

        messages = _respond_messages(
            text,
            self._execute_messages,
            self._observations,
            backdrop=self._backdrop,
        )
        cortex_log(
            "thought respond start",
            task=clip(text, 80),
            message_count=len(messages),
            observations=len(self._observations),
        )
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
                    "thought respond error",
                    error=clip(str(ev.error), 120),
                )
                yield ErrorEvent(error=str(ev.error))
                return
        else:
            cortex_log("thought respond incomplete")
            yield ErrorEvent(error="LLM 流结束但未收到 StreamEndEvent")
            return

        answer = full_text.strip()
        if not answer:
            cortex_log("thought respond empty")
            yield ErrorEvent(error="未能生成最终回复")
            return

        cortex_log(
            "thought respond done",
            answer_len=len(answer),
            prompt_tokens=getattr(usage, "prompt_tokens", None) if usage else None,
            completion_tokens=getattr(usage, "completion_tokens", None) if usage else None,
        )
        yield FinalAnswerEvent(content=answer, usage=usage)

    # ------------------------------------------------------------------
    # 判断与辅助
    # ------------------------------------------------------------------

    def should_replan(self, task: str) -> bool:
        """是否应进入重规划：工具失败，或执行未正常结束（如步数上限）。"""
        if not (task or "").strip():
            return False
        if self._auth_failure_detected:
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

    from agents.prompts import THOUGHT_CONTEXT_SYSTEM
    from memory.context import ContextAssembler

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
        messages = ContextAssembler().assemble(
            system_prompt=THOUGHT_CONTEXT_SYSTEM,
            current_task=query,
        )
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

        async for ev in thought.run_stream(messages):
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
