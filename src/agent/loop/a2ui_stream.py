"""A2UI 流式切分：标签外文本可立刻下发；``<a2ui-json>…</a2ui-json>`` 闭合后再整块解析。"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal

from a2ui.parser.payload_fixer import parse_and_fix
from a2ui.schema.constants import A2UI_CLOSE_TAG, A2UI_OPEN_TAG

from agent.agent_log import agent_trace

EmitKind = Literal["text", "a2ui"]

_FAIL_LOG = Path("logs/a2ui_parse_fail.log")


@dataclass(frozen=True)
class A2uiStreamEmit:
    kind: EmitKind
    text: str = ""
    messages: tuple[dict[str, Any], ...] = ()


def neutralize_smart_quotes(text: str) -> str:
    """把弯引号换成直角引号，避免 payload_fixer 把它们改成 ASCII ``"`` 后截断 JSON 字符串。

    官方 ``_normalize_smart_quotes`` 会把 ``“禁用”`` 变成 ``"禁用"``，若出现在
    JSON 字符串值内部，会直接导致 ``Expecting ',' delimiter``。
    """
    return (
        (text or "")
        .replace("\u201c", "「")
        .replace("\u201d", "」")
        .replace("\u2018", "『")
        .replace("\u2019", "』")
    )


def dump_a2ui_parse_failure(
    *,
    raw: str,
    error: BaseException,
    stage: str,
) -> Path:
    """把失败原文落到 logs，便于对照 char/line 定位。"""
    _FAIL_LOG.parent.mkdir(parents=True, exist_ok=True)
    ts = datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")
    err = str(error)
    # 尽量标出出错位置附近
    snippet = raw
    pos = None
    if hasattr(error, "pos") and isinstance(getattr(error, "pos"), int):
        pos = int(error.pos)  # type: ignore[arg-type]
    elif "char " in err:
        try:
            pos = int(err.rsplit("char ", 1)[-1].rstrip(")"))
        except ValueError:
            pos = None
    focus = ""
    if pos is not None and 0 <= pos <= len(raw):
        lo = max(0, pos - 80)
        hi = min(len(raw), pos + 80)
        focus = f"\n--- around char {pos} ---\n{raw[lo:hi]!r}\n"

    block = (
        f"\n{'=' * 72}\n"
        f"{ts} | stage={stage} | error={err}\n"
        f"{'=' * 72}\n"
        f"{focus}"
        f"--- raw ({len(raw)} chars) ---\n"
        f"{raw}\n"
    )
    with _FAIL_LOG.open("a", encoding="utf-8") as f:
        f.write(block)
    agent_trace(
        "a2ui parse fail dumped",
        stage=stage,
        error=err[:200],
        path=str(_FAIL_LOG.resolve()),
        chars=len(raw),
    )
    return _FAIL_LOG.resolve()


def parse_a2ui_json_block(inner: str, *, stage: str = "block") -> list[dict[str, Any]]:
    """解析单个 ``<a2ui-json>`` 内文；先中和弯引号再走官方 fixer。"""
    cleaned = (inner or "").strip()
    if cleaned.startswith("```json"):
        cleaned = cleaned[len("```json") :]
    elif cleaned.startswith("```"):
        cleaned = cleaned[len("```") :]
    if cleaned.endswith("```"):
        cleaned = cleaned[: -len("```")]
    cleaned = neutralize_smart_quotes(cleaned.strip())
    if not cleaned:
        return []
    try:
        data = parse_and_fix(cleaned)
    except Exception as exc:
        # 若 fixer 抛的是 ValueError 包装，尽量带上底层 JSONDecodeError 位置
        cause = exc.__cause__ or exc
        dump_a2ui_parse_failure(raw=cleaned, error=cause, stage=stage)
        raise
    if isinstance(data, list):
        return [m for m in data if isinstance(m, dict)]
    if isinstance(data, dict):
        return [data]
    return []


def _suffix_is_open_prefix(buf: str) -> int:
    """``buf`` 末尾有多少字符是 OPEN 标签的真前缀（不含完整 OPEN）。"""
    max_n = min(len(buf), len(A2UI_OPEN_TAG) - 1)
    for n in range(max_n, 0, -1):
        if A2UI_OPEN_TAG.startswith(buf[-n:]):
            return n
    return 0


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
            return None

        inner = self._inside[:idx]
        rest = self._inside[idx + len(A2UI_CLOSE_TAG) :]
        self._inside = None
        self._outside = rest

        out: list[A2uiStreamEmit] = []
        msgs = parse_a2ui_json_block(inner, stage="stream_block")
        if msgs:
            out.append(A2uiStreamEmit(kind="a2ui", messages=tuple(msgs)))
        out.extend(self._drain_outside())
        return out
