"""出站 A2A 工具：目录列举 + 委托远程 Agent。"""

from __future__ import annotations

from typing import Any

from a2a_adapter.client.registry import load_agents
from a2a_adapter.client.transport import delegate
from agents.agent_log import a2a_log, clip
from tools.base import BaseTool


class ListAgentsTool(BaseTool):
    """列出 HubloomConfig.a2a.remote_agents 中已配置的远程 Agent。"""

    name = "list_agents"
    description = (
        "列出当前可委托的远程 A2A Agent（静态目录）。"
        "在准备跨 Agent 协作、需要知道有哪些远程助手及其 id 时调用。"
        "返回每项的 id、name、url；后续委托请使用其中的 id 调用 delegate_task。"
    )
    parameters = {
        "type": "object",
        "properties": {},
        "required": [],
    }

    async def execute(self, **_: Any) -> str:
        agents = load_agents()
        a2a_log("tool list_agents", count=len(agents))
        if not agents:
            return (
                "当前未配置远程 Agent。"
                "请在 config/env.yaml 的 a2a.remote_agents 中配置，"
                '例如 [{"id":"hubloom-self","name":"Hubloom","url":"http://127.0.0.1:8001"}]。'
            )

        lines = [f"共 {len(agents)} 个可委托远程 Agent：", ""]
        for i, agent in enumerate(agents, 1):
            lines.append(f"[{i}] id={agent.id}")
            lines.append(f"    name={agent.name}")
            lines.append(f"    url={agent.url}")
            lines.append("")
        lines.append("委托时请使用上方 id，调用 delegate_task。")
        return "\n".join(lines).rstrip() + "\n"


class DelegateTaskTool(BaseTool):
    """向指定远程 A2A Agent 发送任务，返回其最终回答。"""

    name = "delegate_task"
    description = (
        "把任务委托给远程 A2A Agent 并等待最终回答。"
        "先用 list_agents 确认 id；再传入 agent_id 与清晰的 message。"
        "返回值为远程助手的最终 answer 文本（不含其内部过程轨迹）。"
        "适用：本地工具不足以完成、需要另一 Agent 协作时。"
    )
    parameters = {
        "type": "object",
        "properties": {
            "agent_id": {
                "type": "string",
                "description": "远程 Agent 的 id（来自 list_agents），例如 hubloom-self",
            },
            "message": {
                "type": "string",
                "description": "发给远程 Agent 的任务说明，应自包含、简洁明确",
            },
        },
        "required": ["agent_id", "message"],
    }

    async def execute(
        self,
        agent_id: str = "",
        message: str = "",
        **_: Any,
    ) -> str:
        aid = (agent_id or "").strip()
        msg = (message or "").strip()
        if not aid:
            return "agent_id 不能为空。请先调用 list_agents 获取可用 id。"
        if not msg:
            return "message 不能为空。请写清要委托的任务。"

        from hubloom.context import is_a2a_inbound

        if is_a2a_inbound():
            a2a_log("tool delegate_task blocked inbound", agent_id=aid)
            return (
                "委托被拒绝：当前是入站 A2A 回合，禁止再次调用 delegate_task，"
                "以避免 Agent 互委托死循环。请直接使用本地工具完成任务。"
            )

        a2a_log(
            "tool delegate_task",
            agent_id=aid,
            message=clip(msg, 80),
        )
        try:
            from hubloom.context import emit_remote_process

            def _on_event(channel: str, text: str) -> None:
                if channel == "status":
                    emit_remote_process("status", status=text)
                else:
                    emit_remote_process(channel, text)

            answer = await delegate(aid, msg, echo_live=False, on_event=_on_event)
        except KeyError as exc:
            a2a_log("tool delegate_task unknown agent", agent_id=aid)
            return f"委托失败：{exc}"
        except Exception as exc:
            a2a_log("tool delegate_task error", agent_id=aid, error=str(exc))
            return f"委托失败：{type(exc).__name__}: {exc}"

        a2a_log(
            "tool delegate_task done",
            agent_id=aid,
            answer_len=len(answer or ""),
            answer=clip(answer or "", 80),
        )
        text = (answer or "").strip()
        return text if text else "(远程 Agent 返回空回答)"
