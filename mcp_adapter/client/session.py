"""MCP stdio 客户端：连接网关 server.py，发现/调用工具。"""

from __future__ import annotations

import asyncio
import time
from contextlib import AsyncExitStack
from typing import Any

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from mcp_adapter.client.result import parse_call_tool_result, tool_input_schema
from mcp_adapter.log import clip_text, dumps_clip, mcp_log
from tools.tool_result import ToolTransportResult


class MCPToolClient:
    """通过子进程 stdio 与 MCP Server（网关）通信。"""

    def __init__(
        self,
        command: str,
        args: list[str],
        env: dict[str, str] | None = None,
        cwd: str | None = None,
        timeout: float = 120.0,
    ) -> None:
        self.server_params = StdioServerParameters(
            command=command,
            args=args,
            env=env,
            cwd=cwd,
        )
        self.timeout = timeout
        self._session: ClientSession | None = None
        self._exit_stack: AsyncExitStack | None = None

    async def connect(self) -> None:
        if self._exit_stack is not None:
            raise RuntimeError("MCPToolClient is already connected.")

        stack = AsyncExitStack()
        await stack.__aenter__()
        try:
            read, write = await stack.enter_async_context(
                stdio_client(self.server_params)
            )
            session = await stack.enter_async_context(ClientSession(read, write))
            await asyncio.wait_for(session.initialize(), timeout=self.timeout)
        except BaseException:
            await stack.__aexit__(None, None, None)
            raise

        self._exit_stack = stack
        self._session = session

    async def close(self) -> None:
        if self._exit_stack is not None:
            await self._exit_stack.__aexit__(None, None, None)
            self._exit_stack = None
        self._session = None

    async def list_tools(self) -> list[dict[str, Any]]:
        if not self._session:
            raise RuntimeError("MCP client not connected. Call connect() first.")

        result = await asyncio.wait_for(
            self._session.list_tools(),
            timeout=self.timeout,
        )
        tools: list[dict[str, Any]] = []
        for tool in result.tools:
            tools.append(
                {
                    "name": tool.name,
                    "description": tool.description or f"Remote tool: {tool.name}",
                    "parameters": tool_input_schema(tool),
                }
            )
        return tools

    async def execute_tool(
        self,
        tool_name: str,
        arguments: dict[str, Any],
    ) -> ToolTransportResult:
        """调用 MCP 工具，返回传输层结果。"""
        if not self._session:
            raise RuntimeError("MCP client not connected. Call connect() first.")

        mcp_log("tool start", tool=tool_name, args=dumps_clip(arguments))
        start = time.monotonic()
        try:
            result = await asyncio.wait_for(
                self._session.call_tool(tool_name, arguments),
                timeout=self.timeout,
            )
            transport = parse_call_tool_result(
                result,
                tool_name=tool_name,
                arguments=arguments,
            )
        except Exception as exc:
            elapsed_ms = int((time.monotonic() - start) * 1000)
            mcp_log(
                "tool failed",
                tool=tool_name,
                error=clip_text(str(exc)),
                elapsed_ms=elapsed_ms,
            )
            raise

        elapsed_ms = int((time.monotonic() - start) * 1000)
        fields: dict[str, Any] = {
            "tool": tool_name,
            "transport_ok": transport.transport_ok,
            "elapsed_ms": elapsed_ms,
        }
        if transport.http_status is not None:
            fields["http_status"] = transport.http_status
        if transport.http_reason:
            fields["http_reason"] = transport.http_reason
        if transport.transport_ok:
            fields["result"] = clip_text(transport.to_llm_text())
        else:
            fields["error"] = clip_text(transport.error or transport.to_llm_text())
        mcp_log("tool done", **fields)
        return transport

    async def execute_tool_text(
        self,
        tool_name: str,
        arguments: dict[str, Any],
    ) -> str:
        return (await self.execute_tool(tool_name, arguments)).to_llm_text()


async def _demo() -> None:
    from pathlib import Path

    root = Path(__file__).resolve().parents[2]
    server = root / "mcp_adapter" / "server.py"

    client = MCPToolClient(
        command="uv",
        args=["run", "python", str(server)],
        cwd=str(root),
    )
    await client.connect()
    try:
        tools = await client.list_tools()
        print(f"发现 {len(tools)} 个元工具:", [t["name"] for t in tools])
        print()
        from mcp_adapter.gateway.catalog import format_catalog_for_prompt, load_catalog

        catalog = await load_catalog()
        print(format_catalog_for_prompt(catalog))
    finally:
        await client.close()


if __name__ == "__main__":
    asyncio.run(_demo())
