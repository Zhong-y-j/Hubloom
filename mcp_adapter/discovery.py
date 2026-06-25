from __future__ import annotations

from dataclasses import dataclass
from typing import Any, List, Optional

from .client import MCPToolClient


@dataclass(frozen=True)
class MCPBindings:
    """一次 MCP stdio 连接上发现的工具集合与客户端句柄。

    使用完毕后请 ``await bindings.client.close()``，避免子进程泄漏。
    """

    tools: List[Any]
    client: MCPToolClient


async def load_mcp_tools(
    command: str,
    args: List[str],
    env: Optional[dict[str, str]] = None,
    cwd: Optional[str] = None,
) -> MCPBindings:
    """启动 MCP 服务器，发现并包装为 ``MCPTool`` 列表。

    Args:
        command: 启动命令，如 ``"npx"``
        args: 命令参数，如 ``["-y", "@modelcontextprotocol/server-github"]``
        env: 可选的环境变量；合并策略由 ``StdioServerParameters`` / MCP 默认环境决定

    Returns:
        MCPBindings: ``tools`` 与共享的 ``client``；须在适当时机关闭 ``client``。
    """
    # 延后导入，避免 ``tools.builtin`` 与 ``mcp_adapter`` 循环依赖
    from tools.builtin import MCPTool

    client = MCPToolClient(command=command, args=args, env=env, cwd=cwd)
    await client.connect()

    raw_tools = await client.list_tools()
    tools: List[MCPTool] = []
    for raw in raw_tools:
        name = raw.get("name")
        if not name:
            continue
        desc = raw.get("description", f"Remote tool: {name}")
        params = raw.get("parameters", {"type": "object", "properties": {}})
        tools.append(MCPTool(name, desc, params, client))

    return MCPBindings(tools=tools, client=client)
