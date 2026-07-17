"""从最终回复中提取 A2UI 消息；并清洗误写入思考流的 A2UI。

最终回复约定（Thought respond）：
- 优先官网风格：一个或多个 ``<a2ui-json>...</a2ui-json>``，每块为单条消息或消息数组
- 兼容旧约定：``---a2ui_JSON---`` 后跟 JSON 数组
- 亦可整段就是 JSON 消息数组

流式：每闭合一个 ``</a2ui-json>`` 即下发 ``A2uiMessagesEvent(replace=False)``；
turn 结束再下发权威全量 ``replace=True``（含工具数据绑定）。

Chat / 思考过程：应为 Markdown；若误带 A2UI，思考流会剥离。
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
from agents.a2ui_bind import bind_tool_data_to_a2ui_messages
from agents.agent_log import clip, cortex_log

_A2UI_TAG_RE = re.compile(
    r"<a2ui-json>\s*([\s\S]*?)\s*</a2ui-json>",
    re.IGNORECASE,
)

_A2UI_DELIMITER_RE = re.compile(
    r"(?m)(?:^|\n)[ \t]*-{3,}[ \t]*a2ui_JSON[ \t]*-{0,}[ \t]*(?:\r?\n)?",
    re.IGNORECASE,
)

_A2UI_TAG_OPEN_RE = re.compile(r"<a2ui-json\b[^>]*>", re.IGNORECASE)

_A2UI_MSG_KEYS = frozenset(
    {"createSurface", "updateComponents", "updateDataModel", "deleteSurface"}
)

_HOLD_MAX = 48

_A2UI_TAG_CLOSE = re.compile(r"</a2ui-json\s*>", re.IGNORECASE)

_JSON_DECODER = json.JSONDecoder()


def _normalize_message(item: dict[str, Any]) -> dict[str, Any] | None:
    keys = _A2UI_MSG_KEYS.intersection(item.keys())
    if len(keys) != 1:
        return None
    out = dict(item)
    ver = str(out.get("version") or "").strip()
    if ver == "v0.9":
        out["version"] = "v0.9.1"
    elif not ver:
        out["version"] = "v0.9.1"
    return out


def _coerce_messages(data: Any) -> tuple[list[dict[str, Any]] | None, str | None]:
    if isinstance(data, dict):
        data = [data]
    if not isinstance(data, list):
        return None, "a2ui payload must be a JSON array or object"
    if not data:
        return None, "a2ui payload array is empty"
    normalized: list[dict[str, Any]] = []
    for i, item in enumerate(data):
        if not isinstance(item, dict):
            return None, f"a2ui message[{i}] must be an object"
        msg = _normalize_message(item)
        if msg is None:
            return None, (
                f"a2ui message[{i}] must contain exactly one of "
                f"{sorted(_A2UI_MSG_KEYS)}"
            )
        normalized.append(msg)
    return normalized, None


def parse_a2ui_payload(raw: str) -> tuple[list[dict[str, Any]] | None, str | None]:
    """解析 JSON 数组/单对象；容忍外层 Markdown 代码围栏。"""
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
    return _coerce_messages(data)


def extract_a2ui_messages(
    text: str,
) -> tuple[str, list[dict[str, Any]] | None, str | None]:
    """从完整回复提取 A2UI。

    Returns:
        (markdown_outside, messages_or_none, error_or_none)
    """
    raw = text or ""

    tag_bodies = [m.group(1).strip() for m in _A2UI_TAG_RE.finditer(raw) if m.group(1)]
    if tag_bodies:
        messages: list[dict[str, Any]] = []
        for body in tag_bodies:
            part, err = parse_a2ui_payload(body)
            if err or not part:
                return (
                    _A2UI_TAG_RE.sub("", raw).strip(),
                    None,
                    err or "empty a2ui tag",
                )
            messages.extend(part)
        outside = _A2UI_TAG_RE.sub("", raw).strip()
        return outside, messages, None

    match = _A2UI_DELIMITER_RE.search(raw)
    if match:
        markdown = raw[: match.start()].rstrip()
        payload = raw[match.end() :]
        messages, err = parse_a2ui_payload(payload)
        return markdown, messages, err

    stripped = raw.strip()
    if stripped.startswith("[") or stripped.startswith("{"):
        messages, err = parse_a2ui_payload(stripped)
        if messages:
            return "", messages, None
        if err and stripped.startswith("["):
            return raw.strip(), None, err

    return raw.strip(), None, None


def split_a2ui_reply(text: str) -> tuple[str, list[dict[str, Any]] | None, str | None]:
    """兼容旧名：同 ``extract_a2ui_messages``。"""
    return extract_a2ui_messages(text)


class A2uiStreamSplitter:
    """流式切分：安全文本 vs A2UI 缓冲。

    官网 ``<a2ui-json>``：每闭合一块即可 ``drain_completed_a2ui``。
    旧 delimiter / 裸 JSON：等 ``finish_final`` 整包解析。
    """

    def __init__(self) -> None:
        self._mode = "markdown"  # markdown | a2ui
        self._tail = ""
        self._emitted_markdown = ""
        self._a2ui_buf = ""
        self._streamed_count = 0

    @property
    def in_a2ui_mode(self) -> bool:
        return self._mode == "a2ui"

    @property
    def streamed_count(self) -> int:
        return self._streamed_count

    def feed_delta(self, delta: str) -> list[str]:
        if not delta:
            return []
        if self._mode == "a2ui":
            self._a2ui_buf += delta
            return []

        self._tail += delta
        out: list[str] = []

        tag = _A2UI_TAG_OPEN_RE.search(self._tail)
        delim = _A2UI_DELIMITER_RE.search(self._tail)
        cut = None
        if tag and delim:
            cut = tag if tag.start() <= delim.start() else delim
        elif tag:
            cut = tag
        elif delim:
            cut = delim

        if cut is not None:
            before = self._tail[: cut.start()]
            after = self._tail[cut.start() :]
            if before:
                self._emitted_markdown += before
                out.append(before)
            self._mode = "a2ui"
            self._a2ui_buf = after
            self._tail = ""
            return out

        if len(self._tail) > _HOLD_MAX:
            emit = self._tail[:-_HOLD_MAX]
            self._tail = self._tail[-_HOLD_MAX:]
            if emit:
                self._emitted_markdown += emit
                out.append(emit)
        return out

    def flush_hold(self) -> list[str]:
        if self._mode != "markdown" or not self._tail:
            return []
        emit = self._tail
        self._tail = ""
        self._emitted_markdown += emit
        return [emit]

    def drain_completed_a2ui(self) -> list[dict[str, Any]]:
        """取出可下发的 A2UI 消息（闭合标签，或未闭合标签内已完整的 JSON 对象）。"""
        if self._mode != "a2ui" or not self._a2ui_buf:
            return []

        out: list[dict[str, Any]] = []
        buf = self._a2ui_buf
        while True:
            m = _A2UI_TAG_RE.search(buf)
            if not m:
                break
            if buf[: m.start()].strip():
                break
            body = m.group(1).strip()
            if not body or body == "[]":
                buf = buf[m.end() :]
                continue
            part, err = parse_a2ui_payload(body)
            if err or not part:
                cortex_log(
                    "a2ui tag parse failed mid-stream",
                    error=clip(err or "empty", 160),
                )
                buf = buf[m.end() :]
                continue
            out.extend(part)
            buf = buf[m.end() :]

        # 未闭合的 <a2ui-json>：从数组/单对象中 raw_decode 已完整的消息
        partial, buf = _drain_open_tag_objects(buf)
        out.extend(partial)

        self._a2ui_buf = buf
        if out:
            self._streamed_count += len(out)
        return out

    def try_parse_a2ui(self) -> list[dict[str, Any]] | None:
        blob = self._a2ui_buf if self._mode == "a2ui" else self._tail
        if not blob.strip():
            return None
        _, messages, err = extract_a2ui_messages(blob)
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
        tool_results: list[tuple[str, str, bool]] | None = None,
    ) -> list[AgentEvent]:
        pending = self.drain_completed_a2ui()

        markdown, messages, err = extract_a2ui_messages(full_content)
        events: list[AgentEvent] = []
        tools = tool_results or []

        display_md = ""
        if messages:
            bound = bind_tool_data_to_a2ui_messages(messages, tools)
            events.append(A2uiMessagesEvent(messages=bound, replace=True))
            cortex_log(
                "a2ui messages extracted",
                count=len(bound),
                source="final",
                streamed=self._streamed_count,
            )
        elif fallback_messages:
            bound = bind_tool_data_to_a2ui_messages(fallback_messages, tools)
            events.append(A2uiMessagesEvent(messages=bound, replace=True))
            cortex_log(
                "a2ui messages salvaged from thought",
                count=len(bound),
            )
        else:
            if pending:
                bound = bind_tool_data_to_a2ui_messages(pending, tools)
                events.append(A2uiMessagesEvent(messages=bound, replace=False))
            display_md = markdown
            already = self._emitted_markdown
            if display_md.startswith(already):
                rest = display_md[len(already) :]
                if rest:
                    events.append(FinalAnswerDeltaEvent(delta=rest))
            elif already and display_md and not display_md.startswith(already):
                cortex_log(
                    "a2ui split markdown mismatch",
                    emitted=clip(already, 80),
                    authoritative=clip(display_md, 80),
                )
            if err:
                cortex_log("a2ui parse failed", error=clip(err, 160))

        events.append(FinalAnswerEvent(content=display_md, usage=usage))
        return events


def _message_from_json_value(obj: Any) -> list[dict[str, Any]]:
    if isinstance(obj, dict):
        msg = _normalize_message(obj)
        return [msg] if msg else []
    if isinstance(obj, list):
        part, _err = _coerce_messages(obj)
        return part or []
    return []


def _drain_open_tag_objects(buf: str) -> tuple[list[dict[str, Any]], str]:
    """从尚未闭合的 ``<a2ui-json>`` 中抽出已完整的 JSON 对象（支持数组流式）。"""
    open_m = _A2UI_TAG_OPEN_RE.search(buf)
    if not open_m:
        return [], buf
    if buf[: open_m.start()].strip():
        return [], buf
    # 已有完整闭合对则交给外层 TAG_RE；此处只处理开着的缓冲
    if _A2UI_TAG_CLOSE.search(buf, open_m.end()):
        return [], buf

    content_start = open_m.end()
    rest = buf[content_start:]
    lead = 0
    while lead < len(rest) and rest[lead] in " \t\n\r":
        lead += 1
    if lead >= len(rest):
        return [], buf

    out: list[dict[str, Any]] = []
    payload = rest[lead:]

    if payload.startswith("["):
        pos = 1
        while True:
            while pos < len(payload) and payload[pos] in " \t\n\r,":
                pos += 1
            if pos >= len(payload) or payload[pos] == "]":
                break
            try:
                obj, end = _JSON_DECODER.raw_decode(payload, pos)
            except json.JSONDecodeError:
                break
            out.extend(_message_from_json_value(obj))
            pos = end
        new_buf = buf[:content_start] + rest[:lead] + "[" + payload[pos:]
        return out, new_buf

    if payload.startswith("{"):
        try:
            obj, end = _JSON_DECODER.raw_decode(payload, 0)
        except json.JSONDecodeError:
            return [], buf
        out.extend(_message_from_json_value(obj))
        new_buf = buf[:content_start] + rest[:lead] + payload[end:]
        return out, new_buf

    return [], buf


def _yield_streamed_a2ui(
    splitter: A2uiStreamSplitter,
    tool_results: list[tuple[str, str, bool]],
) -> list[A2uiMessagesEvent]:
    completed = splitter.drain_completed_a2ui()
    if not completed:
        return []
    bound = bind_tool_data_to_a2ui_messages(completed, tool_results)
    cortex_log("a2ui messages streamed", count=len(bound))
    # 一条消息一个 SSE，便于前端按条 processMessages
    return [A2uiMessagesEvent(messages=[m], replace=False) for m in bound]


async def map_a2ui_events(
    source: AsyncIterator[AgentEvent],
) -> AsyncIterator[AgentEvent]:
    """包装 Thought 事件流：清洗思考区 A2UI，切分最终回复，绑定工具数据。"""
    final_splitter = A2uiStreamSplitter()
    thought_splitter = A2uiStreamSplitter()
    thought_phase: str | None = None
    salvaged: list[dict[str, Any]] | None = None
    tool_results: list[tuple[str, str, bool]] = []

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
        elif isinstance(ev, ToolResultEvent):
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
            tool_results.append((ev.tool_name, ev.result, ev.is_error))
            yield ev
        elif isinstance(ev, ToolCallEvent):
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
            for a2ui_ev in _yield_streamed_a2ui(final_splitter, tool_results):
                yield a2ui_ev
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
                tool_results=tool_results,
            ):
                yield out
        else:
            yield ev
