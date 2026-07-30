"""Exec Gate：Playbook 硬校验（Step 4）。"""

from __future__ import annotations

from dataclasses import dataclass

from agent.actions import (
    ActAction,
    AskAction,
    AwaitConfirmAction,
    FinishAction,
    TypedAction,
)
from agent.policy import Playbook, PlaybookProgress


@dataclass(frozen=True)
class GateVerdict:
    allow: bool
    code: str = ""
    reason: str = ""
    fused: bool = False


def check_action(
    action: TypedAction,
    playbook: Playbook | None,
    progress: PlaybookProgress,
) -> GateVerdict:
    """Decide 之后、Exec/结束之前调用。reject 不是终态（除非熔断）。"""
    if playbook is None or playbook.is_empty():
        return GateVerdict(allow=True)

    if isinstance(action, AskAction):
        return GateVerdict(allow=True)

    if isinstance(action, AwaitConfirmAction):
        return GateVerdict(allow=True)

    if isinstance(action, ActAction):
        for call in action.tool_calls:
            name = call.name
            if name in playbook.forbid_tools:
                return _reject_or_fuse(
                    progress,
                    code="forbid_tool",
                    reason=f"Playbook 禁止调用工具 `{name}`",
                )
            if name in playbook.confirm_tools and not progress.confirmed:
                return _reject_or_fuse(
                    progress,
                    code="need_confirm",
                    reason=(
                        f"工具 `{name}` 须先 agent_await_confirm，"
                        "用户确认后再 act"
                    ),
                )
        return GateVerdict(allow=True)

    if isinstance(action, FinishAction):
        missing = [
            s.id
            for s in playbook.require_steps
            if s.id not in progress.completed_steps
        ]
        if missing:
            detail = ", ".join(missing)
            return _reject_or_fuse(
                progress,
                code="require_steps",
                reason=(
                    f"尚有必经步骤未完成，禁止 finish：{detail}。"
                    "请先调用规程要求的业务工具。"
                ),
            )
        return GateVerdict(allow=True)

    return GateVerdict(allow=True)


def _reject_or_fuse(
    progress: PlaybookProgress,
    *,
    code: str,
    reason: str,
) -> GateVerdict:
    n = progress.note_reject(code)
    fused = n >= progress.fuse_limit
    if fused:
        return GateVerdict(
            allow=False,
            code=code,
            reason=f"{reason}（同因 reject 已达熔断阈值 {progress.fuse_limit}）",
            fused=True,
        )
    return GateVerdict(allow=False, code=code, reason=reason, fused=False)
