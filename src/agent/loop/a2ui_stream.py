"""A2UI 流式切分：标签外文本可立刻下发；``<a2ui-json>…</a2ui-json>`` 闭合后再整块解析。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

from a2ui.parser.payload_fixer import parse_and_fix
from a2ui.schema.constants import A2UI_CLOSE_TAG, A2UI_OPEN_TAG

EmitKind = Literal["text", "a2ui"]


@dataclass(frozen=True)
class A2uiStreamEmit:
    kind: EmitKind
    text: str = ""
    messages: tuple[dict[str, Any], ...] = ()


def _suffix_is_open_prefix(buf: str) -> int:
    """``buf`` 末尾有多少字符是 OPEN 标签的真前缀（不含完整 OPEN）。"""
    max_n = min(len(buf), len(A2UI_OPEN_TAG) - 1)
    for n in range(max_n, 0, -1):
        if A2UI_OPEN_TAG.startswith(buf[-n:]):
            return n
    return 0


def _parse_block_inner(inner: str) -> list[dict[str, Any]]:
    cleaned = (inner or "").strip()
    if cleaned.startswith("```json"):
        cleaned = cleaned[len("```json") :]
    elif cleaned.startswith("```"):
        cleaned = cleaned[len("```") :]
    if cleaned.endswith("```"):
        cleaned = cleaned[: -len("```")]
    cleaned = cleaned.strip()
    if not cleaned:
        return []
    data = parse_and_fix(cleaned)
    if isinstance(data, list):
        return [m for m in data if isinstance(m, dict)]
    if isinstance(data, dict):
        return [data]
    return []


class A2uiStreamSplitter:
    """增量喂入模型 delta，产出可见文本或已闭合的 A2UI 消息。"""

    def __init__(self) -> None:
        self._outside = ""  # 尚未判定的标签外缓冲（含可能的 OPEN 前缀）
        self._inside: str | None = None  # None=在标签外；str=标签内累计（不含 OPEN）

    def feed(self, delta: str) -> list[A2uiStreamEmit]:
        if not delta:
            return []
        out: list[A2uiStreamEmit] = []
        i = 0
        while i < len(delta):
            if self._inside is None:
                # 拼进 outside，再尽量吐出安全文本
                self._outside += delta[i:]
                i = len(delta)
                out.extend(self._drain_outside())
            else:
                self._inside += delta[i:]
                i = len(delta)
                closed = self._try_close_inside()
                if closed is not None:
                    out.extend(closed)
        return out

    def flush(self) -> list[A2uiStreamEmit]:
        """流结束：未闭合块丢弃（由全文权威 parse 兜底）；标签外残余当文本发出。"""
        out: list[A2uiStreamEmit] = []
        if self._inside is None and self._outside:
            text = self._outside
            self._outside = ""
            if text:
                out.append(A2uiStreamEmit(kind="text", text=text))
        # 半截 <a2ui-json> 不当可见文本发出
        self._inside = None
        self._outside = ""
        return out

    def _drain_outside(self) -> list[A2uiStreamEmit]:
        out: list[A2uiStreamEmit] = []
        while self._inside is None and self._outside:
            idx = self._outside.find(A2UI_OPEN_TAG)
            if idx >= 0:
                before = self._outside[:idx]
                if before:
                    out.append(A2uiStreamEmit(kind="text", text=before))
                # OPEN 之后的内容全部进入标签内缓冲
                self._inside = self._outside[idx + len(A2UI_OPEN_TAG) :]
                self._outside = ""
                closed = self._try_close_inside()
                if closed is not None:
                    out.extend(closed)
                continue

            hold = _suffix_is_open_prefix(self._outside)
            if hold:
                safe = self._outside[:-hold]
                self._outside = self._outside[-hold:]
            else:
                safe = self._outside
                self._outside = ""
            if safe:
                out.append(A2uiStreamEmit(kind="text", text=safe))
            break
        return out

    def _try_close_inside(self) -> list[A2uiStreamEmit] | None:
        """若标签内已有 CLOSE，解析并切回标签外；否则返回 None（继续等）。"""
        if self._inside is None:
            return None
        idx = self._inside.find(A2UI_CLOSE_TAG)
        if idx < 0:
            # 可能 CLOSE 被截断在末尾
            return None

        inner = self._inside[:idx]
        rest = self._inside[idx + len(A2UI_CLOSE_TAG) :]
        self._inside = None
        self._outside = rest

        out: list[A2uiStreamEmit] = []
        try:
            msgs = _parse_block_inner(inner)
        except Exception:
            msgs = []
        if msgs:
            out.append(
                A2uiStreamEmit(kind="a2ui", messages=tuple(msgs))
            )
        # rest 可能还有文本或下一个 OPEN
        out.extend(self._drain_outside())
        return out
