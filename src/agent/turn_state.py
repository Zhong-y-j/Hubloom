"""本轮 run / 人机等待态：表单提交须绑定 run_id；新消息可覆盖等待中的表单。

约定见 ``docs/Hubloom-回合交互契约.md``。
"""

from __future__ import annotations

import threading
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Literal

Resolution = Literal[
    "submit",
    "cancel",
    "superseded_by_message",
]


def new_run_id() -> str:
    return f"run-{uuid.uuid4().hex[:12]}"


def new_tool_call_id() -> str:
    """人机表单对应的虚拟 toolCallId（对齐 AG-UI）。"""
    return f"tc-{uuid.uuid4().hex[:12]}"


# 客户端人机表单虚拟工具名（非 MCP）；出站 TOOL_CALL_* / 入站 tool 消息共用
A2UI_ACTION_TOOL_NAME = "hubloom.a2ui_action"


@dataclass
class PendingInteraction:
    """某会话上「等待人机」的交互（通常是本轮 A2UI 表单）。"""

    session_id: str
    run_id: str
    kind: str = "a2ui"
    status: str = "waiting"  # waiting | 已 resolve 后不应再留在 store
    created_at: float = field(default_factory=time.time)
    meta: dict[str, Any] = field(default_factory=dict)


class TurnStateStore:
    """进程内按 session 保存至多一个 waiting 交互。"""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._pending: dict[str, PendingInteraction] = {}

    def get_pending(self, session_id: str) -> PendingInteraction | None:
        sid = (session_id or "").strip()
        if not sid:
            return None
        with self._lock:
            cur = self._pending.get(sid)
            if cur is None or cur.status != "waiting":
                return None
            return cur

    def begin_run(self, session_id: str, *, run_id: str | None = None) -> str:
        """开始一轮 Agent run，返回 run_id（不自动清除 waiting；先调 supersede）。"""
        sid = (session_id or "").strip()
        if not sid:
            raise ValueError("session_id 不能为空")
        rid = (run_id or "").strip() or new_run_id()
        return rid

    def supersede_if_waiting(
        self,
        session_id: str,
        *,
        reason: Resolution = "superseded_by_message",
    ) -> PendingInteraction | None:
        """若存在 waiting：取消并返回旧交互（新用户消息走对话补全时用）。"""
        sid = (session_id or "").strip()
        if not sid:
            return None
        with self._lock:
            cur = self._pending.get(sid)
            if cur is None or cur.status != "waiting":
                return None
            cur.status = reason
            self._pending.pop(sid, None)
            return cur

    def mark_waiting(
        self,
        session_id: str,
        run_id: str,
        *,
        kind: str = "a2ui",
        meta: dict[str, Any] | None = None,
    ) -> PendingInteraction:
        """本轮需要人机（如表单）：绑定 session + run_id。"""
        sid = (session_id or "").strip()
        rid = (run_id or "").strip()
        if not sid or not rid:
            raise ValueError("session_id 与 run_id 不能为空")
        pending = PendingInteraction(
            session_id=sid,
            run_id=rid,
            kind=(kind or "a2ui").strip() or "a2ui",
            status="waiting",
            meta=dict(meta or {}),
        )
        with self._lock:
            self._pending[sid] = pending
        return pending

    def validate_action(self, session_id: str, run_id: str) -> PendingInteraction:
        """提交/取消前校验：必须指向当前 waiting 的同一 run_id。"""
        sid = (session_id or "").strip()
        rid = (run_id or "").strip()
        if not sid or not rid:
            raise ValueError("action 须带 session_id 与 run_id")
        with self._lock:
            cur = self._pending.get(sid)
            if cur is None or cur.status != "waiting":
                raise ValueError(
                    "当前没有等待中的表单/交互；请先由 Agent 本轮给出表单，"
                    "或改用自然语言继续说明"
                )
            if cur.run_id != rid:
                raise ValueError(
                    f"run_id 与当前等待中的交互不一致："
                    f"expect={cur.run_id!r} got={rid!r}（可能是旧表单，请刷新或重开）"
                )
            return cur

    def resolve_action(
        self,
        session_id: str,
        run_id: str,
        *,
        resolution: Literal["submit", "cancel"],
    ) -> PendingInteraction:
        """校验通过后结束 waiting（入站 action 时调用）。"""
        with self._lock:
            cur = self.validate_action(session_id, run_id)
            cur.status = resolution
            self._pending.pop((session_id or "").strip(), None)
            return cur

    def clear(self, session_id: str) -> None:
        sid = (session_id or "").strip()
        if not sid:
            return
        with self._lock:
            self._pending.pop(sid, None)


# 示例站 / 单进程 Runtime 共用
default_turn_store = TurnStateStore()


def answer_parts_need_human(answer_parts: list[dict[str, Any]] | None) -> bool:
    """终局 answer_parts 里是否仍有 A2UI（需要人机）。"""
    for part in answer_parts or []:
        if not isinstance(part, dict):
            continue
        if part.get("type") == "a2ui":
            return True
    return False
