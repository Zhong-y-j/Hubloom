"""启动 / 连接 MCP backend，供 Agent 元工具或独立客户端使用。"""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Sequence

from mcp_adapter.client.registry import MultiMcpRegistry
from mcp_adapter.client.session import MCPToolClient
from mcp_adapter.config.models import McpEndpoint


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
    timeout: float = 120.0,
) -> MCPToolClient:
    """启动全量 worker（stdio）并返回已连接的客户端。"""
    child_env = dict(env or {})
    child_env["MCP_SWAGGER_URL"] = swagger_url.strip()
    if base_url and str(base_url).strip():
        child_env["MCP_BASE_URL"] = str(base_url).strip()

    command, args = mcp_full_stdio_cmd()
    work = cwd or str(Path(__file__).resolve().parents[1])
    client = MCPToolClient.stdio(
        command,
        args,
        env=build_mcp_subprocess_env(work, child_env),
        cwd=work,
        timeout=timeout,
    )
    await client.connect()
    return client


async def connect_http_mcp(
    url: str,
    *,
    headers: dict[str, str] | None = None,
    timeout: float = 120.0,
) -> MCPToolClient:
    """连接已部署 / 线上的 Streamable HTTP MCP。"""
    client = MCPToolClient.http(url, headers=headers, timeout=timeout)
    await client.connect()
    return client


async def connect_endpoint(
    endpoint: McpEndpoint,
    *,
    cwd: str | None = None,
) -> MCPToolClient:
    """按 ``McpEndpoint`` 连接一路 MCP（stdio 或 http）。"""
    if endpoint.transport == "http":
        return await connect_http_mcp(
            endpoint.url or "",
            headers=dict(endpoint.headers),
            timeout=endpoint.timeout,
        )
    return await connect_full_mcp(
        swagger_url=endpoint.swagger_url or "",
        base_url=endpoint.base_url,
        env=dict(endpoint.env) or None,
        cwd=cwd,
        timeout=endpoint.timeout,
    )


async def connect_mcp_endpoints(
    endpoints: Sequence[McpEndpoint],
    *,
    cwd: str | None = None,
) -> MultiMcpRegistry:
    """连接多路 MCP，返回注册表；任一路失败时关闭已连上的客户端并抛出。"""
    if not endpoints:
        raise ValueError("endpoints 不能为空")

    seen: set[str] = set()
    clients: dict[str, MCPToolClient] = {}
    try:
        for ep in endpoints:
            sid = ep.id.strip()
            if sid in seen:
                raise ValueError(f"重复的 MCP endpoint id: {sid!r}")
            seen.add(sid)
            clients[sid] = await connect_endpoint(ep, cwd=cwd)
    except BaseException:
        for client in clients.values():
            try:
                await client.close()
            except Exception:  # noqa: BLE001
                pass
        raise

    return MultiMcpRegistry(clients=clients)


async def load_agent_mcp_bindings(
    *,
    swagger_url: str,
    base_url: str | None = None,
    env: dict[str, str] | None = None,
    cwd: str | None = None,
) -> AgentMcpSetup:
    """主路径：catalog + 全量 MCP（stdio）+ 原生 list_api/call_api。

    Runtime 现有调用保持不变；多路 MCP / HTTP 请用 ``connect_mcp_endpoints``。
    """
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
