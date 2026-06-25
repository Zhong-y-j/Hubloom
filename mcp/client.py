import asyncio
from contextlib import AsyncExitStack
from typing import Any, Dict, List, Optional

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


def _tool_input_schema(tool: Any) -> Dict[str, Any]:
    """兼容 MCP SDK 中 Tool 的 schema 字段命名。"""
    raw = getattr(tool, "input_schema", None) or getattr(tool, "inputSchema", None)
    if raw is None:
        return {"type": "object", "properties": {}}
    if isinstance(raw, dict):
        return raw
    if hasattr(raw, "model_dump"):
        return raw.model_dump(by_alias=True, exclude_none=True)
    return dict(raw)


class MCPToolClient:
    """MCP 客户端，通过子进程 stdio 与 MCP Server 通信。

    Args:
        command: 启动服务器的命令，例如 ``"npx"`` 或 ``"python"``
        args: 命令参数，例如 ``["-y", "@modelcontextprotocol/server-github"]``
        env: 可选的环境变量字典
    """

    def __init__(
        self,
        command: str,
        args: List[str],
        env: Optional[Dict[str, str]] = None,
        cwd: Optional[str] = None,
        timeout: float = 30.0,
    ):
        self.server_params = StdioServerParameters(
            command=command,
            args=args,
            env=env,
            cwd=cwd,
        )
        self.timeout = timeout
        self._session: Optional[ClientSession] = None
        self._exit_stack: Optional[AsyncExitStack] = None

    async def connect(self):
        """启动子进程并建立 MCP 会话。

        必须在**同一个** ``asyncio`` 事件循环里完成后续的 ``list_tools`` / ``execute_tool`` /
        ``close``（例如包在一次 ``asyncio.run(main())`` 里）。不要多次调用 ``asyncio.run``，
        否则 AnyIO 的 cancel scope 会报 *different task* / ``ClosedResourceError``。
        """
        if self._exit_stack is not None:
            raise RuntimeError("MCPToolClient is already connected.")

        stack = AsyncExitStack()
        await stack.__aenter__()
        try:
            read, write = await stack.enter_async_context(
                stdio_client(self.server_params)
            )
            session = await stack.enter_async_context(ClientSession(read, write))
            await session.initialize()
        except BaseException:
            await stack.__aexit__(None, None, None)
            raise

        self._exit_stack = stack
        self._session = session

    async def close(self):
        """关闭会话并终止子进程（逆序退出 Session → stdio TaskGroup）。"""
        if self._exit_stack is not None:
            await self._exit_stack.__aexit__(None, None, None)
            self._exit_stack = None
        self._session = None

    async def list_tools(self) -> List[Dict[str, Any]]:
        """获取服务器提供的工具列表。

        Returns:
            list[dict]: 每个工具包含 ``name``, ``description``, ``parameters`` (JSON Schema)
        """
        if not self._session:
            raise RuntimeError("MCP client not connected. Call connect() first.")

        result = await asyncio.wait_for(
            self._session.list_tools(), timeout=self.timeout
        )
        tools = []
        for tool in result.tools:
            tools.append(
                {
                    "name": tool.name,
                    "description": tool.description or f"Remote tool: {tool.name}",
                    "parameters": _tool_input_schema(tool),
                }
            )
        return tools

    async def execute_tool(self, tool_name: str, arguments: Dict[str, Any]) -> str:
        """调用服务器上的指定工具。

        Args:
            tool_name: 工具名称
            arguments: 工具参数字典

        Returns:
            工具执行结果（字符串格式）
        """
        if not self._session:
            raise RuntimeError("MCP client not connected. Call connect() first.")

        result = await asyncio.wait_for(
            self._session.call_tool(tool_name, arguments),
            timeout=self.timeout,
        )
        # 将返回内容拼接为字符串（主要为 TextContent）
        if hasattr(result, "content") and result.content:
            parts: List[str] = []
            for item in result.content:
                text = getattr(item, "text", None)
                if isinstance(text, str):
                    parts.append(text)
                else:
                    parts.append(str(item))
            return "\n".join(parts)
        return str(result)


if __name__ == "__main__":
    from pathlib import Path

    ROOT = Path(__file__).resolve().parent.parent
    SERVER = Path(__file__).resolve().parent / "server.py"

    async def _demo() -> None:
        client = MCPToolClient(
            command="uv",
            args=["run", "python", str(SERVER)],
            cwd=str(ROOT),
        )
        await client.connect()
        try:
            tools = await client.list_tools()
            print(f"发现 {len(tools)} 个工具:", [t["name"] for t in tools])
            print()

            # 1) 无参：日期
            demo_tool = "getInventory"
            out = await client.execute_tool(demo_tool, {})
            print(out)

            # # 2) 换一个接口：列出某城市下所有火车站及 station_code
            # demo2 = "get-stations-code-in-city"
            # out2 = await client.execute_tool(demo2, {"city": "杭州"})
            # print()
            # print(f"--- call_tool({demo2!r}, {{'city': '杭州'}}) ---")
            # text2 = out2 if len(out2) <= 3000 else out2[:3000] + "\n... [截断]"
            # print(text2)

        finally:
            await client.close()

    asyncio.run(_demo())
