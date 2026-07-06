"""测试 MCP 连接：uv run python mcp/test_client.py"""

import asyncio
from pathlib import Path

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

ROOT = Path(__file__).resolve().parent.parent
SERVER = Path(__file__).resolve().parent / "server.py"


async def main() -> None:
    params = StdioServerParameters(
        command="uv",
        args=["run", "python", str(SERVER)],
        cwd=str(ROOT),
    )
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            info = await session.initialize()
            print(f"Connected: {info.serverInfo.name} ({info.protocolVersion})\n")

            tools = (await session.list_tools()).tools
            print(f"Tools ({len(tools)}):")
            for tool in tools:
                print(f"  - {tool.name}:{tool.description}")


if __name__ == "__main__":
    asyncio.run(main())
