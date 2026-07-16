"""从最终回复中切分 Markdown 与 A2UI JSON；并清洗误写入思考流的 A2UI。

约定分隔符（单独成行，横杠数量 ≥ 3）：

```text
---a2ui_JSON---
```

流式策略：
- 最终回复：分隔符前继续 ``FinalAnswerDeltaEvent``；之后缓冲 JSON，结束时发 ``A2uiMessagesEvent``
- 思考过程：同样切开，**不**把 JSON 下发到 thought_delta；若最终回复没有 A2UI，则把思考里解析到的 JSON 提升为 ``A2uiMessagesEvent``
"""

from __future__ import annotations

import json
import re
from collections.abc import AsyncIterator
from typing import Any

from agents.events import (
    A2uiMessagesEvent,
    AgentEvent,
    FinalAnswerDeltaEvent,
    FinalAnswerEvent,
    ThoughtDeltaEvent,
    ToolCallEvent,
    ToolResultEvent,
)
from agents.agent_log import clip, cortex_log

# 允许 3+ 横杠；尾部横杠可省略；容忍行首空白
_A2UI_DELIMITER_RE = re.compile(
    r"(?m)(?:^|\n)[ \t]*-{3,}[ \t]*a2ui_JSON[ \t]*-{0,}[ \t]*(?:\r?\n)?",
    re.IGNORECASE,
)

_A2UI_MSG_KEYS = frozenset(
    {"createSurface", "updateComponents", "updateDataModel", "deleteSurface"}
)

_HOLD_MAX = 48


def split_a2ui_reply(text: str) -> tuple[str, list[dict[str, Any]] | None, str | None]:
    """静态切分完整回复。

    Returns:
        (markdown, messages_or_none, error_or_none)
    """
    raw = text or ""
    match = _A2UI_DELIMITER_RE.search(raw)
    if not match:
        return raw.strip(), None, None

    markdown = raw[: match.start()].rstrip()
    # match 可能吃掉前导 \n，保证 markdown 干净即可
    payload = raw[match.end() :]
    messages, err = parse_a2ui_payload(payload)
    return markdown, messages, err


def parse_a2ui_payload(raw: str) -> tuple[list[dict[str, Any]] | None, str | None]:
    """解析分隔符后的 JSON 数组；容忍外层 Markdown 代码围栏。"""
    text = (raw or "").strip()
    if not text:
        return None, "empty a2ui payload"

    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text, count=1, flags=re.IGNORECASE)
        text = re.sub(r"\s*```\s*$", "", text)
        text = text.strip()

    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        return None, f"invalid json: {exc}"

    if not isinstance(data, list):
        return None, "a2ui payload must be a JSON array"
    if not data:
        return None, "a2ui payload array is empty"

    normalized: list[dict[str, Any]] = []
    for i, item in enumerate(data):
        if not isinstance(item, dict):
            return None, f"a2ui message[{i}] must be an object"
        keys = _A2UI_MSG_KEYS.intersection(item.keys())
        if len(keys) != 1:
            return None, (
                f"a2ui message[{i}] must contain exactly one of "
                f"{sorted(_A2UI_MSG_KEYS)}"
            )
        normalized.append(item)
    return normalized, None


class A2uiStreamSplitter:
    """流式切分：安全文本 vs A2UI 缓冲。"""

    def __init__(self) -> None:
        self._mode = "markdown"  # markdown | a2ui
        self._tail = ""
        self._emitted_markdown = ""

    @property
    def in_a2ui_mode(self) -> bool:
        return self._mode == "a2ui"

    def feed_delta(self, delta: str) -> list[str]:
        """喂入增量，返回可安全下发的文本片段（不含 A2UI JSON）。"""
        if not delta:
            return []
        if self._mode == "a2ui":
            self._tail += delta
            return []

        self._tail += delta
        out: list[str] = []
        match = _A2UI_DELIMITER_RE.search(self._tail)
        if match:
            before = self._tail[: match.start()]
            after = self._tail[match.end() :]
            if before:
                self._emitted_markdown += before
                out.append(before)
            self._mode = "a2ui"
            self._tail = after
            return out

        if len(self._tail) > _HOLD_MAX:
            emit = self._tail[:-_HOLD_MAX]
            self._tail = self._tail[-_HOLD_MAX:]
            if emit:
                self._emitted_markdown += emit
                out.append(emit)
        return out

    def flush_hold(self) -> list[str]:
        """阶段切换时冲掉 markdown 侧 hold（不冲 a2ui 缓冲）。"""
        if self._mode != "markdown" or not self._tail:
            return []
        emit = self._tail
        self._tail = ""
        self._emitted_markdown += emit
        return [emit]

    def try_parse_a2ui(self) -> list[dict[str, Any]] | None:
        if self._mode != "a2ui":
            return None
        messages, err = parse_a2ui_payload(self._tail)
        if messages:
            return messages
        if err:
            cortex_log("a2ui buffer parse failed", error=clip(err, 160))
        return None

    def finish_final(
        self,
        full_content: str,
        usage: Any = None,
        *,
        fallback_messages: list[dict[str, Any]] | None = None,
    ) -> list[AgentEvent]:
        markdown, messages, err = split_a2ui_reply(full_content)
        events: list[AgentEvent] = []

        already = self._emitted_markdown
        if markdown.startswith(already):
            rest = markdown[len(already) :]
            if rest:
                events.append(FinalAnswerDeltaEvent(delta=rest))
        elif already and markdown and not markdown.startswith(already):
            cortex_log(
                "a2ui split markdown mismatch",
                emitted=clip(already, 80),
                authoritative=clip(markdown, 80),
            )

        if messages:
            events.append(A2uiMessagesEvent(messages=messages))
            cortex_log("a2ui messages extracted", count=len(messages), source="final")
        elif fallback_messages:
            events.append(A2uiMessagesEvent(messages=fallback_messages))
            cortex_log(
                "a2ui messages salvaged from thought",
                count=len(fallback_messages),
            )
        elif err:
            cortex_log("a2ui parse failed", error=clip(err, 160))

        events.append(FinalAnswerEvent(content=markdown, usage=usage))
        return events


async def map_a2ui_events(
    source: AsyncIterator[AgentEvent],
) -> AsyncIterator[AgentEvent]:
    """包装 Chat/Thought 事件流：清洗思考区 A2UI，切分最终回复。"""
    final_splitter = A2uiStreamSplitter()
    thought_splitter = A2uiStreamSplitter()
    thought_phase: str | None = None
    salvaged: list[dict[str, Any]] | None = None

    async for ev in source:
        if isinstance(ev, ThoughtDeltaEvent):
            if thought_phase is not None and ev.phase != thought_phase:
                for chunk in thought_splitter.flush_hold():
                    yield ThoughtDeltaEvent(phase=thought_phase, delta=chunk)
                parsed = thought_splitter.try_parse_a2ui()
                if parsed:
                    salvaged = parsed
                    cortex_log(
                        "a2ui stripped from thought",
                        phase=thought_phase,
                        count=len(parsed),
                    )
                thought_splitter = A2uiStreamSplitter()
            thought_phase = ev.phase
            for chunk in thought_splitter.feed_delta(ev.delta):
                yield ThoughtDeltaEvent(phase=ev.phase, delta=chunk)
        elif isinstance(ev, (ToolCallEvent, ToolResultEvent)):
            if thought_phase is not None:
                for chunk in thought_splitter.flush_hold():
                    yield ThoughtDeltaEvent(phase=thought_phase, delta=chunk)
            parsed = thought_splitter.try_parse_a2ui()
            if parsed:
                salvaged = parsed
                cortex_log(
                    "a2ui stripped from thought",
                    phase=thought_phase or "",
                    count=len(parsed),
                )
            thought_splitter = A2uiStreamSplitter()
            thought_phase = None
            yield ev
        elif isinstance(ev, FinalAnswerDeltaEvent):
            if thought_phase is not None:
                for chunk in thought_splitter.flush_hold():
                    yield ThoughtDeltaEvent(phase=thought_phase, delta=chunk)
                parsed = thought_splitter.try_parse_a2ui()
                if parsed:
                    salvaged = parsed
                thought_splitter = A2uiStreamSplitter()
                thought_phase = None
            for chunk in final_splitter.feed_delta(ev.delta):
                yield FinalAnswerDeltaEvent(delta=chunk)
        elif isinstance(ev, FinalAnswerEvent):
            if thought_phase is not None:
                for chunk in thought_splitter.flush_hold():
                    yield ThoughtDeltaEvent(phase=thought_phase, delta=chunk)
                parsed = thought_splitter.try_parse_a2ui()
                if parsed:
                    salvaged = parsed
                thought_phase = None
            for out in final_splitter.finish_final(
                ev.content,
                ev.usage,
                fallback_messages=salvaged,
            ):
                yield out
        else:
            yield ev
