"""A2A 执行层：Task 状态机；业务通过 run_turn 注入。

流式约定：
- answer → 主 Artifact（最终回答）
- thought / tool_* / phase → 名为 trace 的第二 Artifact（过程）
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from uuid import uuid4

from a2a.helpers import new_task_from_user_message, new_text_message, new_text_part
from a2a.server.agent_execution import AgentExecutor, RequestContext
from a2a.server.events import EventQueue
from a2a.server.tasks import TaskUpdater
from a2a.types import TaskState

from agents.agent_log import a2a_log, clip
from a2a_adapter.server.mapping import message_to_text, text_to_artifact_parts

# (channel, text) → 写出分片；channel 见 bridge
OnStream = Callable[[str, str], Awaitable[None]]
# (query, task_id, on_stream) -> 完整 reply
RunTurn = Callable[[str, str, OnStream], Awaitable[str]]

_TRACE_CHANNELS = frozenset({"thought", "tool_call", "tool_result", "phase"})


async def _echo_turn(query: str, task_id: str, on_stream: OnStream) -> str:
    body = query or "(empty)"
    reply = f"我是Hubloom，我收到了你的消息: {body}"
    await on_stream("answer", reply)
    return reply


class HubloomExecutor(AgentExecutor):
    def __init__(self, run_turn: RunTurn | None = None) -> None:
        self._run_turn = run_turn or _echo_turn

    async def execute(self, context: RequestContext, event_queue: EventQueue) -> None:
        task = context.current_task or new_task_from_user_message(context.message)
        if not context.current_task:
            await event_queue.enqueue_event(task)

        updater = TaskUpdater(
            event_queue=event_queue,
            task_id=task.id,
            context_id=task.context_id,
        )

        await updater.update_status(
            state=TaskState.TASK_STATE_WORKING,
            message=new_text_message("Processing…"),
        )

        answer_id = str(uuid4())
        trace_id = str(uuid4())
        answer_chunks = 0
        trace_chunks = 0

        async def _write(
            *,
            artifact_id: str,
            name: str | None,
            text: str,
            index: int,
        ) -> int:
            await updater.add_artifact(
                parts=[new_text_part(text=text, media_type="text/plain")],
                artifact_id=artifact_id,
                name=name,
                append=(index > 0),
                last_chunk=False,
            )
            return index + 1

        async def on_stream(channel: str, text: str) -> None:
            nonlocal answer_chunks, trace_chunks
            if not text:
                return
            if channel == "answer":
                answer_chunks = await _write(
                    artifact_id=answer_id,
                    name="answer",
                    text=text,
                    index=answer_chunks,
                )
            elif channel in _TRACE_CHANNELS:
                trace_chunks = await _write(
                    artifact_id=trace_id,
                    name="trace",
                    text=text,
                    index=trace_chunks,
                )

        try:
            query = message_to_text(context.message)
            a2a_log(
                "executor start",
                task_id=task.id,
                context_id=task.context_id,
                query=clip(query, 80),
            )
            reply = await self._run_turn(query, task.id, on_stream)

            if answer_chunks == 0:
                await updater.add_artifact(
                    parts=text_to_artifact_parts(reply),
                    artifact_id=answer_id,
                    name="answer",
                    append=False,
                    last_chunk=True,
                )
            else:
                await updater.add_artifact(
                    parts=[new_text_part(text="", media_type="text/plain")],
                    artifact_id=answer_id,
                    name="answer",
                    append=True,
                    last_chunk=True,
                )

            if trace_chunks > 0:
                await updater.add_artifact(
                    parts=[new_text_part(text="", media_type="text/plain")],
                    artifact_id=trace_id,
                    name="trace",
                    append=True,
                    last_chunk=True,
                )

            await updater.update_status(
                state=TaskState.TASK_STATE_COMPLETED,
                message=new_text_message("Done."),
            )
            a2a_log(
                "executor completed",
                task_id=task.id,
                answer_chunks=answer_chunks,
                trace_chunks=trace_chunks,
                reply_len=len(reply or ""),
            )
        except Exception as exc:
            a2a_log("executor failed", task_id=task.id, error=str(exc))
            await updater.update_status(
                state=TaskState.TASK_STATE_FAILED,
                message=new_text_message(f"Failed: {exc}"),
            )

    async def cancel(self, context: RequestContext, event_queue: EventQueue) -> None:
        raise NotImplementedError("cancel not supported")
