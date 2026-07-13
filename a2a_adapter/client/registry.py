"""静态远程 Agent 目录（出站用）。发现远程 Agent 的配置信息。

配置：环境变量 A2A_REMOTE_AGENTS，JSON 数组，例如：
  [{"id":"hubloom-self","name":"Hubloom","url":"http://127.0.0.1:8001"}]

可选字段 token：出站 Authorization Bearer。
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass


@dataclass(frozen=True)
class RemoteAgent:
    id: str
    name: str
    url: str
    token: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(self, "url", (self.url or "").rstrip("/"))


def load_agents() -> list[RemoteAgent]:
    """从 A2A_REMOTE_AGENTS 加载；未配置或解析失败 → 空列表。"""
    raw = (os.getenv("A2A_REMOTE_AGENTS") or "").strip()
    if not raw:
        return []
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValueError(f"A2A_REMOTE_AGENTS 不是合法 JSON: {exc}") from exc
    if not isinstance(data, list):
        raise ValueError("A2A_REMOTE_AGENTS 必须是 JSON 数组")

    agents: list[RemoteAgent] = []
    for i, item in enumerate(data):
        if not isinstance(item, dict):
            raise ValueError(f"A2A_REMOTE_AGENTS[{i}] 必须是对象")
        agent_id = str(item.get("id") or "").strip()
        url = str(item.get("url") or item.get("card_url") or "").strip()
        name = str(item.get("name") or agent_id).strip()
        token = str(item.get("token") or "").strip()
        if not agent_id or not url:
            raise ValueError(f"A2A_REMOTE_AGENTS[{i}] 需要 id 与 url")
        agents.append(RemoteAgent(id=agent_id, name=name, url=url, token=token))
    return agents


def get_agent(agent_id: str) -> RemoteAgent | None:
    key = (agent_id or "").strip()
    if not key:
        return None
    for agent in load_agents():
        if agent.id == key:
            return agent
    return None


if __name__ == "__main__":
    for a in load_agents():
        print(a)
    print("count =", len(load_agents()))
