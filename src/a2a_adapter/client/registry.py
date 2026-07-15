"""静态远程 Agent 目录（出站用）。

由 ``HubloomConfig.a2a_remote_agents``（或等价 JSON 字符串）经
``configure_agents`` / ``load_agents(raw=...)`` 注入；不读环境变量。
"""

from __future__ import annotations

import json
from dataclasses import dataclass

_configured_raw: str | None = None


@dataclass(frozen=True)
class RemoteAgent:
    id: str
    name: str
    url: str
    token: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(self, "url", (self.url or "").rstrip("/"))


def configure_agents(raw: str | None) -> None:
    """进程级注入远程目录（Hubloom create 时调用）。传 None/空则清空。"""
    global _configured_raw
    text = (raw or "").strip()
    _configured_raw = text or None


def parse_agents(raw: str | None) -> list[RemoteAgent]:
    """解析 JSON 数组字符串为 RemoteAgent 列表；空 → []。"""
    text = (raw or "").strip()
    if not text:
        return []
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ValueError(f"a2a.remote_agents 不是合法 JSON: {exc}") from exc
    if not isinstance(data, list):
        raise ValueError("a2a.remote_agents 必须是 JSON 数组")

    agents: list[RemoteAgent] = []
    for i, item in enumerate(data):
        if not isinstance(item, dict):
            raise ValueError(f"a2a.remote_agents[{i}] 必须是对象")
        agent_id = str(item.get("id") or "").strip()
        url = str(item.get("url") or item.get("card_url") or "").strip()
        name = str(item.get("name") or agent_id).strip()
        token = str(item.get("token") or "").strip()
        if not agent_id or not url:
            raise ValueError(f"a2a.remote_agents[{i}] 需要 id 与 url")
        agents.append(RemoteAgent(id=agent_id, name=name, url=url, token=token))
    return agents


def load_agents(raw: str | None = None) -> list[RemoteAgent]:
    """加载远程目录。

    - 显式传入 ``raw`` → 解析该字符串
    - 否则用 ``configure_agents`` 注入的配置
    """
    if raw is not None:
        return parse_agents(raw)
    return parse_agents(_configured_raw)


def get_agent(agent_id: str, *, raw: str | None = None) -> RemoteAgent | None:
    key = (agent_id or "").strip()
    if not key:
        return None
    for agent in load_agents(raw):
        if agent.id == key:
            return agent
    return None


if __name__ == "__main__":
    from hubloom.config import HubloomConfig

    cfg = HubloomConfig.from_file("config/env.yaml")
    configure_agents(cfg.a2a_remote_agents)
    for a in load_agents():
        print(a)
    print("count =", len(load_agents()))
