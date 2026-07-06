"""启动 MCP 网关子进程，发现工具并包装为 MCPTool。"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from mcp_adapter.client.session import MCPToolClient


def build_mcp_subprocess_env(
    cwd: str | None = None,
    env: dict[str, str] | None = None,
) -> dict[str, str]:
    """构造 MCP Server 子进程环境，确保项目根在 PYTHONPATH 中。"""
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
    """一次 MCP stdio 连接上发现的工具集合与客户端句柄。

    使用完毕后请 ``await bindings.client.close()``，避免子进程泄漏。
    """

    tools: list[Any]
    client: MCPToolClient


async def load_mcp_tools(
    command: str,
    args: list[str],
    env: dict[str, str] | None = None,
    cwd: str | None = None,
) -> MCPBindings:
    """启动 MCP 服务器，发现并包装为 ``MCPTool`` 列表。"""
    # 延后导入，避免 tools.builtin 与 mcp_adapter 循环依赖
    from tools.builtin import MCPTool

    client = MCPToolClient(
        command=command,
        args=args,
        env=build_mcp_subprocess_env(cwd, env),
        cwd=cwd,
    )
    await client.connect()

    raw_tools = await client.list_tools()
    tools: list[MCPTool] = []
    for raw in raw_tools:
        name = raw.get("name")
        if not name:
            continue
        desc = raw.get("description", f"Remote tool: {name}")
        params = raw.get("parameters", {"type": "object", "properties": {}})
        tools.append(MCPTool(name, desc, params, client))

    return MCPBindings(tools=tools, client=client)
