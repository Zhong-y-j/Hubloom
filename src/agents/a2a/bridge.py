"""A2A → ADP：把一轮用户文本交给 CortexAgent。

对外推送两类流：
- answer：最终回答增量（FinalAnswerDelta）
- thought / tool_call / tool_result / phase：Thought 过程

session / token 来自凭证层（A2 侧身份），不由 A1 传入。
"""

from __future__ import annotations

import json
from collections.abc import Awaitable, Callable

from agents.a2a.credential import Credential, resolve_credential
from agents.agent_log import a2a_log, clip
from agents.api.display import resolve_tool_display_name
from agents.api.events import compact_tool_result
from agents.api.request_context import (
    clear_request_context,
    set_a2a_inbound,
    set_request_context,
)
from hubloom.runtime import CortexRuntime
from hubloom.session import format_session_id
from agents.events import (
    ErrorEvent,
    FinalAnswerDeltaEvent,
    FinalAnswerEvent,
    PhaseEvent,
    RemoteProcessEvent,
    ThoughtDeltaEvent,
    ToolCallEvent,
    ToolResultEvent,
)

# channel: answer | thought | tool_call | tool_result | phase
OnStream = Callable[[str, str], Awaitable[None]]


async def run_a2a_turn(
    runtime: CortexRuntime,
    query: str,
    *,
    task_id: str,
    credential: Credential | None = None,
    on_stream: OnStream | None = None,
) -> str:
    """
    1. 凭证层得到 A2 user_id + token（联调为静态假值）
    2. session 用 user_id（与 Chat 一用户一会话对齐）；token 写入 context 供 MCP
    3. run_stream；过程与最终回答经 on_stream 推出
    """
    cred = credential or resolve_credential()
    # create_agent 用短键；request_context 用 mem: 模板（与 /v1/chat 一致）
    session_key = cred.user_id
    session_id = format_session_id(session_key)
    set_request_context(session_id=session_id, bearer_token=cred.token)
    # 入站回合：禁止再向外 delegate，避免 A↔B 互委托死循环
    set_a2a_inbound(True)
    agent = runtime.create_agent(session_key)

    a2a_log(
        "bridge turn start",
        task_id=task_id,
        user_id=cred.user_id,
        session_id=session_id,
        has_token=bool(cred.token),
        a2a_inbound=True,
        query=clip(query, 80),
    )

    final = ""
    answer_streamed = False
    tool_calls = 0

    async def _emit(channel: str, text: str) -> None:
        if on_stream is None or not text:
            return
        await on_stream(channel, text)

    try:
        async for ev in agent.run_stream(query):
            if isinstance(ev, ErrorEvent):
                a2a_log("bridge agent error", task_id=task_id, error=clip(ev.error, 120))
                raise RuntimeError(ev.error)

            if isinstance(ev, PhaseEvent):
                a2a_log(
                    "bridge phase",
                    task_id=task_id,
                    phase=ev.phase,
                    route=ev.route,
                )
                await _emit("phase", f"[{ev.phase}] route={ev.route}\n")

            elif isinstance(ev, ThoughtDeltaEvent) and ev.delta:
                await _emit("thought", ev.delta)

            elif isinstance(ev, ToolCallEvent):
                tool_calls += 1
                name = resolve_tool_display_name(ev.tool_name, ev.args)
                args = json.dumps(ev.args or {}, ensure_ascii=False)
                a2a_log(
                    "bridge tool_call",
                    task_id=task_id,
                    tool=name,
                    args=clip(args, 120),
                )
                await _emit("tool_call", f"\n[tool_call] {name} {args}\n")

            elif isinstance(ev, ToolResultEvent):
                body = compact_tool_result(ev.result, max_len=4000)
                tag = "ERROR" if ev.is_error else "ok"
                a2a_log(
                    "bridge tool_result",
                    task_id=task_id,
                    tool=ev.tool_name,
                    is_error=ev.is_error,
                    result_len=len(ev.result or ""),
                )
                await _emit(
                    "tool_result",
                    f"[tool_result:{tag}] {ev.tool_name}\n{body}\n",
                )

            elif isinstance(ev, RemoteProcessEvent):
                if ev.channel == "status" and ev.status:
                    await _emit("thought", f"[remote:{ev.agent_id}] {ev.status}\n")
                elif ev.delta:
                    await _emit("thought", ev.delta)

            elif isinstance(ev, FinalAnswerDeltaEvent) and ev.delta:
                answer_streamed = True
                await _emit("answer", ev.delta)

            elif isinstance(ev, FinalAnswerEvent) and ev.content:
                final = ev.content
    finally:
        clear_request_context()

    if on_stream is not None and not answer_streamed and final:
        await on_stream("answer", final)

    if not final:
        outcome = agent.get_last_outcome()
        if outcome is not None:
            final = outcome.final_answer or ""
    reply = final.strip() or "(empty)"
    a2a_log(
        "bridge turn done",
        task_id=task_id,
        user_id=cred.user_id,
        tool_calls=tool_calls,
        answer_len=len(reply),
        answer=clip(reply, 80),
    )
    return reply
