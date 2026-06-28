import asyncio
from contextlib import AsyncExitStack
from typing import Any, Dict, List, Optional

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from tools.tool_result import ToolTransportResult, build_transport_result


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


def _extract_text_content(result: Any) -> str:
    parts: List[str] = []
    content = getattr(result, "content", None) or []
    for item in content:
        text = getattr(item, "text", None)
        if isinstance(text, str):
            parts.append(text)
        else:
            parts.append(str(item))
    return "\n".join(parts).strip()


def _parse_call_tool_result(
    result: Any,
    *,
    tool_name: str,
    arguments: Dict[str, Any],
) -> ToolTransportResult:
    if getattr(result, "isError", False):
        err_text = _extract_text_content(result)
        return build_transport_result(
            tool_name=tool_name,
            arguments=arguments,
            transport_ok=False,
            error=err_text or f"Tool {tool_name!r} returned MCP error",
        )

    http_status: int | None = None
    http_reason: str | None = None
    body = ""

    structured = getattr(result, "structuredContent", None)
    if isinstance(structured, dict):
        if "_http_status" in structured:
            try:
                http_status = int(structured["_http_status"])
            except (TypeError, ValueError):
                http_status = None
        if isinstance(structured.get("_http_reason"), str):
            http_reason = structured["_http_reason"]
        payload = {
            k: v
            for k, v in structured.items()
            if k not in {"_http_status", "_http_reason"}
        }
        if payload:
            import json

            body = json.dumps(payload, ensure_ascii=False)
        elif http_status is not None:
            body = ""

    if not body:
        body = _extract_text_content(result)

    return build_transport_result(
        tool_name=tool_name,
        arguments=arguments,
        transport_ok=True,
        http_status=http_status,
        http_reason=http_reason,
        body=body,
    )


class MCPToolClient:
    """MCP 客户端，通过子进程 stdio 与 MCP Server 通信。"""

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
        if self._exit_stack is not None:
            await self._exit_stack.__aexit__(None, None, None)
            self._exit_stack = None
        self._session = None

    async def list_tools(self) -> List[Dict[str, Any]]:
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

    async def execute_tool(
        self, tool_name: str, arguments: Dict[str, Any]
    ) -> ToolTransportResult:
        """调用 MCP 工具，返回传输层结果（含 HTTP 状态与 body）。"""
        if not self._session:
            raise RuntimeError("MCP client not connected. Call connect() first.")

        result = await asyncio.wait_for(
            self._session.call_tool(tool_name, arguments),
            timeout=self.timeout,
        )
        return _parse_call_tool_result(
            result, tool_name=tool_name, arguments=arguments
        )

    async def execute_tool_text(
        self, tool_name: str, arguments: Dict[str, Any]
    ) -> str:
        """兼容旧接口：返回供 LLM 解读的 JSON 文本。"""
        return (await self.execute_tool(tool_name, arguments)).to_llm_text()


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
            out = await client.execute_tool("getInventory", {})
            print(out.to_llm_text())
        finally:
            await client.close()

    asyncio.run(_demo())
