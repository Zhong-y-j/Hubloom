"""Hubloom Agent（Policy-Bounded Typed ReAct · Step 3）。

注意：本包 ``__init__`` 保持轻量，避免 ``agent.agent_log`` ↔ ``memory`` 循环导入。
常用符号请从子模块导入，或通过 ``__getattr__`` 懒加载。
"""

from __future__ import annotations

from typing import Any

__all__ = [
    "ActAction",
    "AgentEvent",
    "AskAction",
    "AwaitConfirmAction",
    "AwaitingUserEvent",
    "CONTROL_ASK",
    "CONTROL_CONFIRM",
    "CONTROL_FINISH",
    "EvidenceJournal",
    "ErrorEvent",
    "FinalAnswerEvent",
    "FinishAction",
    "InMemorySessionStore",
    "PendingState",
    "Playbook",
    "PolicyRejectEvent",
    "RunCompleteEvent",
    "RunResult",
    "StepEvent",
    "TypedAction",
    "build_agent_systems",
    "cancel_awaiting",
    "compile_playbook_from_skills",
    "control_tool_definitions",
    "parse_decide_output",
    "resume_stream",
    "run_stream",
    "run_stream_v2",
]


def __getattr__(name: str) -> Any:
    if name in {
        "CONTROL_ASK",
        "CONTROL_CONFIRM",
        "CONTROL_FINISH",
        "ActAction",
        "AskAction",
        "AwaitConfirmAction",
        "FinishAction",
        "TypedAction",
        "control_tool_definitions",
        "parse_decide_output",
    }:
        import agent.actions as actions

        return getattr(actions, name)
    if name in {
        "AgentEvent",
        "ErrorEvent",
        "FinalAnswerEvent",
        "StepEvent",
        "RunCompleteEvent",
        "AwaitingUserEvent",
        "PolicyRejectEvent",
    }:
        import agent.events as events

        return getattr(events, name)
    if name in {"Playbook", "compile_playbook_from_skills"}:
        import agent.policy as policy

        return getattr(policy, name)
    if name == "EvidenceJournal":
        from agent.evidence import EvidenceJournal

        return EvidenceJournal
    if name in {"InMemorySessionStore", "PendingState", "cancel_awaiting"}:
        import agent.session as session

        return getattr(session, name)
    if name in {"RunResult", "run_stream", "run_stream_v2", "resume_stream"}:
        import agent.run as run

        return getattr(run, name)
    if name == "build_agent_systems":
        from agent.assemble import build_agent_systems

        return build_agent_systems
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
