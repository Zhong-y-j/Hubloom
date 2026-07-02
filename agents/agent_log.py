"""Agent 链路结构化日志（loguru / observability.log）。"""

from __future__ import annotations

import os
from contextvars import ContextVar

from observability import log as _log

_turn_id: ContextVar[str] = ContextVar("cortex_turn_id", default="")


def set_turn_id(turn_id: str) -> None:
    _turn_id.set(turn_id)


def clear_turn_id() -> None:
    _turn_id.set("")


def clip(text: str | None, n: int = 160) -> str:
    s = (text or "").strip().replace("\n", "\\n")
    if len(s) <= n:
        return s
    return s[:n] + f"…(+{len(s) - n})"


def _enabled(env_var: str) -> bool:
    if os.getenv("CORTEX_AGENT_LOG", "").lower() in ("1", "true", "yes"):
        return True
    return os.getenv(env_var, "").lower() in ("1", "true", "yes")


def _emit(prefix: str, env_var: str, message: str, /, **fields) -> None:
    if not _enabled(env_var):
        return
    tid = _turn_id.get()
    if tid:
        fields = {**fields, "turn_id": tid}
    _log(f"{prefix} {message}", **fields)


def hub_log(message: str, /, **fields) -> None:
    _emit("hub", "CORTEX_HUB_LOG", message, **fields)


def plan_log(message: str, /, **fields) -> None:
    _emit("plan", "CORTEX_PLAN_LOG", message, **fields)


def reflection_log(message: str, /, **fields) -> None:
    _emit("reflection", "CORTEX_REFLECTION_LOG", message, **fields)


def specialist_log(message: str, /, **fields) -> None:
    _emit("specialist", "CORTEX_SPECIALIST_LOG", message, **fields)


def react_log(message: str, /, **fields) -> None:
    _emit("react", "CORTEX_REACT_LOG", message, **fields)


def mcp_log(message: str, /, **fields) -> None:
    _emit("mcp", "CORTEX_MCP_LOG", message, **fields)


def memory_log(message: str, /, **fields) -> None:
    _emit("memory", "CORTEX_MEMORY_LOG", message, **fields)


def cortex_log(message: str, /, **fields) -> None:
    """ADP 编排层日志（CortexAgent / Assessor / Chat / Thought）。"""
    _emit("cortex", "CORTEX_CORTEX_LOG", message, **fields)
