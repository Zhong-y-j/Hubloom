"""启动单个全量 MCP backend，供 Agent 元工具转发。"""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from mcp_adapter.client.session import MCPToolClient


def mcp_full_stdio_cmd() -> tuple[str, list[str]]:
    """启动单个全量 OpenAPI MCP（``worker --full``）。"""
    return sys.executable, ["-m", "mcp_adapter.server.worker", "--full"]


def build_mcp_subprocess_env(
    cwd: str | None = None,
    env: dict[str, str] | None = None,
) -> dict[str, str]:
    """构造 MCP Server 子进程环境，确保 cwd 在 PYTHONPATH 中。"""
    merged = dict(os.environ)
    if env:
        merged.update(env)
    root = str(Path(cwd or os.getcwd()).resolve())
    existing = merged.get("PYTHONPATH", "")
    parts = [p for p in existing.split(os.pathsep) if p]
    if root not in parts:
        parts.insert(0, root)
    merged["PYTHONPATH"] = os.pathsep.join(parts)
    return merged


@dataclass(frozen=True)
class MCPBindings:
    """一次 MCP 连接上的工具集合与客户端句柄。

    使用完毕后请 ``await bindings.client.close()``，避免子进程泄漏。
    """

    tools: list[Any]
    client: MCPToolClient


@dataclass(frozen=True)
class AgentMcpSetup:
    """Agent 主路径：元工具 + catalog + 全量 MCP 客户端。"""

    bindings: MCPBindings
    catalog: Any  # GatewayCatalog；避免循环类型依赖


async def connect_full_mcp(
    *,
    swagger_url: str,
    base_url: str | None = None,
    env: dict[str, str] | None = None,
    cwd: str | None = None,
) -> MCPToolClient:
    """启动全量 worker 并返回已连接的客户端（不含 Agent 元工具包装）。"""
    child_env = dict(env or {})
    child_env["MCP_SWAGGER_URL"] = swagger_url.strip()
    if base_url and str(base_url).strip():
        child_env["MCP_BASE_URL"] = str(base_url).strip()

    command, args = mcp_full_stdio_cmd()
    work = cwd or str(Path(__file__).resolve().parents[1])
    client = MCPToolClient(
        command=command,
        args=args,
        env=build_mcp_subprocess_env(work, child_env),
        cwd=work,
    )
    await client.connect()
    return client


async def load_agent_mcp_bindings(
    *,
    swagger_url: str,
    base_url: str | None = None,
    env: dict[str, str] | None = None,
    cwd: str | None = None,
) -> AgentMcpSetup:
    """主路径：catalog + 全量 MCP + 原生 list_api/call_api。"""
    from mcp_adapter.gateway.catalog import load_catalog
    from tools.builtin.api_tools import build_api_tools

    catalog = await load_catalog(swagger_url=swagger_url, base_url=base_url)
    client = await connect_full_mcp(
        swagger_url=swagger_url,
        base_url=base_url,
        env=env,
        cwd=cwd,
    )
    bindings = MCPBindings(
        tools=build_api_tools(catalog, client),
        client=client,
    )
    return AgentMcpSetup(bindings=bindings, catalog=catalog)
