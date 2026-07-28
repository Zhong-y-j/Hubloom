"""多路 MCP 注册表：按 id 持有多个已连接客户端。"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from mcp_adapter.client.result import ToolTransportResult
from mcp_adapter.client.session import MCPToolClient

_SEP = "__"


@dataclass
class MultiMcpRegistry:
    """多路 MCP 客户端集合。

    ``list_all_tools(prefix=True)`` 时工具名为 ``{server_id}__{tool_name}``，
    便于 ``execute_prefixed`` 路由，避免不同 Server 工具名冲突。
    """

    clients: dict[str, MCPToolClient] = field(default_factory=dict)

    def get(self, server_id: str) -> MCPToolClient:
        key = (server_id or "").strip()
        if key not in self.clients:
            known = ", ".join(sorted(self.clients)) or "(empty)"
            raise KeyError(f"未知 MCP server id: {key!r}；已知: {known}")
        return self.clients[key]

    @property
    def ids(self) -> list[str]:
        return sorted(self.clients)

    async def list_tools(self, server_id: str) -> list[dict[str, Any]]:
        return await self.get(server_id).list_tools()

    async def list_all_tools(self, *, prefix: bool = True) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        for sid in self.ids:
            tools = await self.clients[sid].list_tools()
            for tool in tools:
                item = dict(tool)
                item["server_id"] = sid
                if prefix:
                    item["name"] = f"{sid}{_SEP}{tool['name']}"
                    item["raw_name"] = tool["name"]
                out.append(item)
        return out

    @staticmethod
    def split_prefixed_name(name: str) -> tuple[str, str]:
        raw = (name or "").strip()
        if _SEP not in raw:
            raise ValueError(
                f"工具名 {name!r} 缺少 server 前缀（期望 {{id}}{_SEP}{{tool}}）"
            )
        sid, tool = raw.split(_SEP, 1)
        if not sid or not tool:
            raise ValueError(f"无效的前缀工具名: {name!r}")
        return sid, tool

    async def execute_tool(
        self,
        server_id: str,
        tool_name: str,
        arguments: dict[str, Any],
        *,
        auth_token: str | None = None,
        auth_scheme: str | None = None,
    ) -> ToolTransportResult:
        return await self.get(server_id).execute_tool(
            tool_name,
            arguments,
            auth_token=auth_token,
            auth_scheme=auth_scheme,
        )

    async def execute_prefixed(
        self,
        prefixed_name: str,
        arguments: dict[str, Any],
        *,
        auth_token: str | None = None,
        auth_scheme: str | None = None,
    ) -> ToolTransportResult:
        sid, tool = self.split_prefixed_name(prefixed_name)
        return await self.execute_tool(
            sid,
            tool,
            arguments,
            auth_token=auth_token,
            auth_scheme=auth_scheme,
        )

    async def close(self) -> None:
        errors: list[BaseException] = []
        for client in self.clients.values():
            try:
                await client.close()
            except BaseException as exc:  # noqa: BLE001 — 尽量关完
                errors.append(exc)
        self.clients.clear()
        if errors:
            raise errors[0]
