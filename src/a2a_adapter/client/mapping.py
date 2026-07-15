"""出站：把 A2A Task / Stream 回包抽成最终 answer 文本。"""

from __future__ import annotations

from a2a.types import StreamResponse, Task, TaskState


def _parts_text(parts) -> str:
    chunks: list[str] = []
    for part in parts or []:
        text = getattr(part, "text", None) or ""
        if text:
            chunks.append(text)
    return "".join(chunks)


def answer_from_task(task: Task) -> str:
    """优先 name=answer 的 Artifact；否则拼所有非 trace 文本；再否则任意文本。"""
    answer_bits: list[str] = []
    other_bits: list[str] = []
    for art in task.artifacts or []:
        name = (art.name or "").strip() or "answer"
        body = _parts_text(art.parts)
        if not body:
            continue
        if name == "answer":
            answer_bits.append(body)
        elif name != "trace":
            other_bits.append(body)
    if answer_bits:
        return "".join(answer_bits).strip()
    if other_bits:
        return "".join(other_bits).strip()
    # 兜底：含 trace 也拼上，避免空结果
    fallback = []
    for art in task.artifacts or []:
        body = _parts_text(art.parts)
        if body:
            fallback.append(body)
    return "".join(fallback).strip()


def collect_answer_from_stream(chunks: list[StreamResponse]) -> str:
    """
    遍历 send_message 的回包：
    - 非流式：通常一个带 task 的 StreamResponse
    - 流式：拼 artifact_update 里 name=answer 的 text，或以最终 task 为准
    """
    answer_parts: list[str] = []
    last_task: Task | None = None
    failed_msg = ""

    for chunk in chunks:
        if chunk.HasField("task"):
            last_task = chunk.task
        if chunk.HasField("artifact_update"):
            upd = chunk.artifact_update
            name = (upd.artifact.name or "").strip() or "answer"
            text = _parts_text(upd.artifact.parts)
            if name == "answer" and text:
                answer_parts.append(text)
        if chunk.HasField("status_update"):
            st = chunk.status_update.status
            if st.state == TaskState.TASK_STATE_FAILED:
                failed_msg = (
                    _parts_text(st.message.parts) if st.message.parts else "task failed"
                )
            if st.state == TaskState.TASK_STATE_COMPLETED and last_task is None:
                # 有的实现只在前面给过 task；保持 last_task
                pass

    if failed_msg:
        raise RuntimeError(failed_msg)

    if last_task is not None:
        from_task = answer_from_task(last_task)
        if from_task:
            return from_task
        # task 里 artifacts 可能不完整，用流式拼接
        if answer_parts:
            return "".join(answer_parts).strip()
        state = last_task.status.state if last_task.status else None
        if state == TaskState.TASK_STATE_FAILED:
            raise RuntimeError("remote task failed")
        return "(empty)"

    if answer_parts:
        return "".join(answer_parts).strip()
    return "(empty)"
