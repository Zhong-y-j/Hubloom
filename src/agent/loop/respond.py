from __future__ import annotations

from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import Literal, Any

from core.models import Message, TokenUsage
from core.provider import (
    DeltaEvent,
    LLMProvider,
    StreamEndEvent,
    StreamErrorEvent,
)

from agent.agent_log import agent_trace
from agent.events import (
    AgentEvent,
    A2uiMessagesEvent,
    ErrorEvent,
    FinalAnswerDeltaEvent,
    FinalAnswerEvent,
)
from agent.loop.a2ui_stream import (
    A2uiStreamEmit,
    A2uiStreamSplitter,
    dump_a2ui_parse_failure,
    neutralize_smart_quotes,
    parse_a2ui_json_block,
)

from a2ui.parser.parser import has_a2ui_parts, parse_response

PresentMode = Literal["markdown", "a2ui", "auto"]


@dataclass
class RespondResult:
    """一轮 Respond 的终态。"""

    content: str = ""
    present_mode: PresentMode = "markdown"
    a2ui_messages: list[dict[str, Any]] = field(default_factory=list)
    usage: TokenUsage | None = None


async def _stream_markdown(
    llm: LLMProvider,
    messages: list[Message],
    *,
    present_mode: PresentMode,
) -> AsyncIterator[AgentEvent | RespondResult]:
    content_parts: list[str] = []
    usage: TokenUsage | None = None

    async for ev in llm.generate_stream(messages=messages, tools=None):
        if isinstance(ev, DeltaEvent):
            if ev.delta:
                content_parts.append(ev.delta)
                yield FinalAnswerDeltaEvent(delta=ev.delta, source="markdown")
        elif isinstance(ev, StreamErrorEvent):
            agent_trace("respond llm error", present_mode=present_mode, error=str(ev.error)[:200])
            yield ErrorEvent(error=str(ev.error))
            content = "".join(content_parts)
            yield FinalAnswerEvent(content=content)
            yield RespondResult(content=content, present_mode=present_mode)
            return
        elif isinstance(ev, StreamEndEvent):
            usage = ev.output.usage
            if not content_parts and ev.output.content:
                content_parts.append(ev.output.content)
                yield FinalAnswerDeltaEvent(delta=ev.output.content, source="markdown")
            break

    content = "".join(content_parts).strip()
    agent_trace(
        "respond llm done",
        present_mode=present_mode,
        content_len=len(content),
        a2ui=0,
    )
    yield FinalAnswerEvent(content=content, usage=usage)
    yield RespondResult(content=content, present_mode=present_mode, usage=usage)


def _extract_a2ui_messages(content: str) -> list[dict[str, Any]]:
    """从完整回复正文切出 A2UI messages（权威全量）。

    先中和弯引号，再按块解析；单块失败会落盘并抛出。
    """
    if not content or not has_a2ui_parts(content):
        return []
    safe = neutralize_smart_quotes(content)
    try:
        messages: list[dict[str, Any]] = []
        for part in parse_response(safe):
            if part.a2ui_json is None:
                continue
            if isinstance(part.a2ui_json, list):
                messages.extend(m for m in part.a2ui_json if isinstance(m, dict))
            elif isinstance(part.a2ui_json, dict):
                messages.append(part.a2ui_json)
        return messages
    except Exception as exc:
        import re

        from a2ui.schema.constants import A2UI_CLOSE_TAG, A2UI_OPEN_TAG

        pattern = re.compile(
            re.escape(A2UI_OPEN_TAG) + r"(.*?)" + re.escape(A2UI_CLOSE_TAG),
            re.DOTALL,
        )
        recovered: list[dict[str, Any]] = []
        last_err: BaseException | None = None
        for i, m in enumerate(pattern.finditer(safe)):
            try:
                recovered.extend(
                    parse_a2ui_json_block(m.group(1), stage=f"extract_block_{i}")
                )
            except Exception as block_exc:
                last_err = block_exc
        if recovered and last_err is None:
            return recovered
        if last_err is not None:
            raise last_err from exc
        dump_a2ui_parse_failure(raw=safe, error=exc, stage="extract_full")
        raise


def user_visible_content(
    content: str,
    *,
    a2ui_messages: list[dict[str, Any]] | None = None,
) -> str:
    """供 UI / 历史落库的可见正文：去掉 ``<a2ui-json>``，纯界面时用占位。

    多段正文会拼成一段（顺序信息见 ``answer_display_parts``）。
    """
    import re

    text = (content or "").strip()
    if text and has_a2ui_parts(text):
        try:
            safe = neutralize_smart_quotes(text)
            chunks: list[str] = []
            for part in parse_response(safe):
                piece = (getattr(part, "text", None) or "").strip()
                if piece:
                    chunks.append(piece)
            text = "\n\n".join(chunks).strip()
        except Exception:
            text = re.sub(
                r"<a2ui-json>[\s\S]*?</a2ui-json>",
                "",
                text,
                flags=re.IGNORECASE,
            )
            text = re.sub(r"\n{3,}", "\n\n", text).strip()
    if not text and a2ui_messages:
        return "（交互界面）"
    return text


def answer_display_parts(
    content: str,
    *,
    a2ui_messages: list[dict[str, Any]] | None = None,
    channel: str | None = None,
) -> list[dict[str, Any]]:
    """从原始 Respond 输出拆出 text / a2ui 交错段，供前端按序渲染。"""
    raw = content or ""
    parts: list[dict[str, Any]] = []

    def _text_part(piece: str) -> dict[str, Any]:
        item: dict[str, Any] = {"type": "text", "text": piece}
        if channel:
            item["channel"] = channel
        return item

    if raw and has_a2ui_parts(raw):
        try:
            safe = neutralize_smart_quotes(raw)
            saw_a2ui = False
            for part in parse_response(safe):
                piece = (getattr(part, "text", None) or "").strip()
                if piece:
                    parts.append(_text_part(piece))
                if getattr(part, "a2ui_json", None) is not None and not saw_a2ui:
                    parts.append({"type": "a2ui"})
                    saw_a2ui = True
            if a2ui_messages and not saw_a2ui:
                parts.append({"type": "a2ui"})
            return parts
        except Exception:
            visible = user_visible_content(raw, a2ui_messages=a2ui_messages)
            if visible and visible != "（交互界面）":
                parts.append(_text_part(visible))
            if a2ui_messages:
                parts.append({"type": "a2ui"})
            return parts

    visible = (raw or "").strip()
    if visible:
        parts.append(_text_part(visible))
    if a2ui_messages:
        parts.append({"type": "a2ui"})
    return parts


async def _emit_splitter_items(
    emits: list[A2uiStreamEmit],
) -> AsyncIterator[AgentEvent]:
    for item in emits:
        if item.kind == "text" and item.text:
            yield FinalAnswerDeltaEvent(delta=item.text, source="a2ui")
        elif item.kind == "a2ui" and item.messages:
            yield A2uiMessagesEvent(
                messages=list(item.messages),
                replace=False,
            )
            agent_trace(
                "a2ui block",
                replace=False,
                n=len(item.messages),
            )


async def _stream_a2ui(
    llm: LLMProvider,
    messages: list[Message],
    *,
    present_mode: PresentMode,
) -> AsyncIterator[AgentEvent | RespondResult]:
    """流式 A2UI：标签外文本即时下发；每个闭合 ``<a2ui-json>`` 整块推送；结束再权威全量。"""
    content_parts: list[str] = []
    usage: TokenUsage | None = None
    splitter = A2uiStreamSplitter()
    incremental_n = 0

    async for ev in llm.generate_stream(messages=messages, tools=None):
        if isinstance(ev, DeltaEvent):
            if not ev.delta:
                continue
            content_parts.append(ev.delta)
            async for item in _emit_splitter_items(splitter.feed(ev.delta)):
                if isinstance(item, A2uiMessagesEvent):
                    incremental_n += len(item.messages)
                yield item
        elif isinstance(ev, StreamErrorEvent):
            agent_trace(
                "respond llm error",
                present_mode=present_mode,
                error=str(ev.error)[:200],
            )
            yield ErrorEvent(error=str(ev.error))
            async for item in _emit_splitter_items(splitter.flush()):
                yield item
            content = "".join(content_parts)
            a2ui_messages = _extract_a2ui_messages(content)
            if a2ui_messages:
                yield A2uiMessagesEvent(messages=a2ui_messages, replace=True)
            yield FinalAnswerEvent(content=content)
            yield RespondResult(
                content=content,
                present_mode=present_mode,
                a2ui_messages=a2ui_messages,
            )
            return
        elif isinstance(ev, StreamEndEvent):
            usage = ev.output.usage
            if not content_parts and ev.output.content:
                content_parts.append(ev.output.content)
                async for item in _emit_splitter_items(splitter.feed(ev.output.content)):
                    if isinstance(item, A2uiMessagesEvent):
                        incremental_n += len(item.messages)
                    yield item
            break

    async for item in _emit_splitter_items(splitter.flush()):
        if isinstance(item, A2uiMessagesEvent):
            incremental_n += len(item.messages)
        yield item

    content = "".join(content_parts).strip()
    a2ui_messages = _extract_a2ui_messages(content)
    if a2ui_messages:
        # 权威全量：与增量结果对齐，前端 replace 重建
        yield A2uiMessagesEvent(messages=a2ui_messages, replace=True)
    agent_trace(
        "respond llm done",
        present_mode=present_mode,
        content_len=len(content),
        a2ui=len(a2ui_messages),
        a2ui_incremental=incremental_n,
    )
    yield FinalAnswerEvent(content=content, usage=usage)
    yield RespondResult(
        content=content,
        present_mode=present_mode,
        a2ui_messages=a2ui_messages,
        usage=usage,
    )


async def respond(
    llm: LLMProvider,
    messages: list[Message],
    *,
    present_mode: PresentMode = "markdown",
) -> AsyncIterator[AgentEvent | RespondResult]:
    """基于当前 messages 生成最终用户回复。

    流式产出 ``FinalAnswerDeltaEvent`` / ``ErrorEvent``，
    结束时再产出 ``FinalAnswerEvent`` 与 ``RespondResult``。

    本步：``markdown`` / ``a2ui`` 已实现；``auto`` 在 Orchestrator 层解析为二者之一后再调用本函数。
    """
    if not messages:
        agent_trace("respond abort", error="empty messages", present_mode=present_mode)
        yield ErrorEvent(error="Respond 收到空 messages")
        yield RespondResult(present_mode=present_mode)
        return

    agent_trace(
        "respond llm start",
        present_mode=present_mode,
        messages=len(messages),
    )

    if present_mode == "markdown":
        async for item in _stream_markdown(llm, messages, present_mode=present_mode):
            yield item
        return

    if present_mode == "a2ui":
        async for item in _stream_a2ui(llm, messages, present_mode=present_mode):
            yield item
        return

    if present_mode == "auto":
        agent_trace("respond abort", error="auto must be resolved before respond()")
        yield ErrorEvent(
            error="present_mode='auto' 应在 run_stream 中解析为 markdown/a2ui 后再调用 respond",
            recoverable=False,
        )
        yield RespondResult(present_mode=present_mode)
        return

    agent_trace("respond abort", error=f"unknown present_mode={present_mode!r}")
    yield ErrorEvent(
        error=f"未知 present_mode={present_mode!r}，可选: markdown / a2ui / auto",
        recoverable=False,
    )
    yield RespondResult(present_mode=present_mode)
