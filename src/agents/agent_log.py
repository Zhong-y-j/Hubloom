"""Agent 链路结构化日志（loguru / observability.log）。

开关由 ``configure_agent_logging`` / HubloomConfig.logging 注入，不读 CORTEX_*_LOG 环境变量。
"""

from __future__ import annotations

from contextvars import ContextVar

from observability import log as _log

_turn_id: ContextVar[str] = ContextVar("cortex_turn_id", default="")

# 进程级开关：agent_log 为总闸；各通道 None 表示跟随总闸
_agent_log: bool = False
_cortex_log: bool | None = None
_a2a_log: bool | None = None
_memory_log: bool | None = None
_mcp_log: bool | None = None
_hub_log: bool | None = None
_plan_log: bool | None = None
_reflection_log: bool | None = None
_specialist_log: bool | None = None
_react_log: bool | None = None


def configure_agent_logging(
    *,
    agent_log: bool | None = None,
    cortex_log: bool | None = None,
    a2a_log: bool | None = None,
    memory_log: bool | None = None,
    mcp_log: bool | None = None,
) -> None:
    """由 Hubloom create / runtime 注入日志开关。"""
    global _agent_log, _cortex_log, _a2a_log, _memory_log, _mcp_log
    if agent_log is not None:
        _agent_log = bool(agent_log)
    _cortex_log = cortex_log
    _a2a_log = a2a_log
    _memory_log = memory_log
    _mcp_log = mcp_log


def set_turn_id(turn_id: str) -> None:
    _turn_id.set(turn_id)


def clear_turn_id() -> None:
    _turn_id.set("")


def clip(text: str | None, n: int = 160) -> str:
    s = (text or "").strip().replace("\n", "\\n")
    if len(s) <= n:
        return s
    return s[:n] + f"…(+{len(s) - n})"


def _channel_on(flag: bool | None) -> bool:
    """总闸开则全开；否则仅当该通道显式 True。"""
    if _agent_log:
        return True
    return bool(flag)


def _emit(prefix: str, enabled: bool, message: str, /, **fields) -> None:
    if not enabled:
        return
    tid = _turn_id.get()
    if tid:
        fields = {**fields, "turn_id": tid}
    _log(f"{prefix} {message}", **fields)


def hub_log(message: str, /, **fields) -> None:
    _emit("hub", _channel_on(_hub_log), message, **fields)


def plan_log(message: str, /, **fields) -> None:
    _emit("plan", _channel_on(_plan_log), message, **fields)


def reflection_log(message: str, /, **fields) -> None:
    _emit("reflection", _channel_on(_reflection_log), message, **fields)


def specialist_log(message: str, /, **fields) -> None:
    _emit("specialist", _channel_on(_specialist_log), message, **fields)


def react_log(message: str, /, **fields) -> None:
    _emit("react", _channel_on(_react_log), message, **fields)


def mcp_log(message: str, /, **fields) -> None:
    _emit("mcp", _channel_on(_mcp_log), message, **fields)


def memory_log(message: str, /, **fields) -> None:
    _emit("memory", _channel_on(_memory_log), message, **fields)


def cortex_log(message: str, /, **fields) -> None:
    """ADP 编排层日志（Hubloom / Assessor / Chat / Thought）。"""
    _emit("cortex", _channel_on(_cortex_log), message, **fields)


def a2a_log(message: str, /, **fields) -> None:
    """A2A 入站日志（Executor / bridge / credential）。"""
    _emit("a2a", _channel_on(_a2a_log), message, **fields)
