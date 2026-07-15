"""MCP stdio 客户端：连接全量 backend worker（或旧网关），发现/调用工具。"""

from __future__ import annotations

import asyncio
import os
import threading
import time
from contextlib import AsyncExitStack
from pathlib import Path
from typing import Any, TextIO

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from mcp_adapter.auth import auth_trace, build_auth_meta, resolve_auth_token
from mcp_adapter.client.result import (
    ToolTransportResult,
    parse_call_tool_result,
    tool_input_schema,
)
from mcp_adapter.log import clip_text, dumps_clip, mcp_log


def _worker_errlog() -> TextIO:
    """子进程 stderr 落到 logs/mcp-worker.stderr.log，避免刷父终端。"""
    log_dir = Path("logs")
    try:
        log_dir.mkdir(parents=True, exist_ok=True)
        return open(log_dir / "mcp-worker.stderr.log", "a", encoding="utf-8")
    except OSError:
        return open(os.devnull, "w", encoding="utf-8")


class MCPToolClient:
    """通过子进程 stdio 与 MCP Server（全量 worker）通信。

    stdio 客户端的 anyio cancel scope 必须在同一 asyncio task 内进入/退出，
    因此连接生命周期运行在独立后台事件循环中。
    """

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
        self._errlog: TextIO | None = None
        self._bg_loop: asyncio.AbstractEventLoop | None = None
        self._bg_thread: threading.Thread | None = None
        self._bg_ready = threading.Event()

    def _ensure_bg_loop(self) -> asyncio.AbstractEventLoop:
        if self._bg_loop is not None:
            return self._bg_loop

        def _runner() -> None:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            self._bg_loop = loop
            self._bg_ready.set()
            loop.run_forever()

        self._bg_thread = threading.Thread(
            target=_runner,
            name="mcp-backend-client",
            daemon=True,
        )
        self._bg_thread.start()
        self._bg_ready.wait()
        assert self._bg_loop is not None
        return self._bg_loop

    async def _call_bg(self, coro: Any) -> Any:
        loop = self._ensure_bg_loop()
        return await asyncio.wrap_future(asyncio.run_coroutine_threadsafe(coro, loop))

    async def _connect_impl(self) -> None:
        if self._exit_stack is not None:
            raise RuntimeError("MCPToolClient is already connected.")

        stack = AsyncExitStack()
        await stack.__aenter__()
        try:
            # MCP_WORKER_STDERR=1 时把子进程日志打到父终端，便于调试
            if (os.getenv("MCP_WORKER_STDERR") or "").strip().lower() in {
                "1",
                "true",
                "yes",
            }:
                read, write = await stack.enter_async_context(
                    stdio_client(self.server_params)
                )
            else:
                self._errlog = _worker_errlog()
                stack.callback(self._errlog.close)
                read, write = await stack.enter_async_context(
                    stdio_client(self.server_params, errlog=self._errlog)
                )
            session = await stack.enter_async_context(ClientSession(read, write))
            await asyncio.wait_for(session.initialize(), timeout=self.timeout)
        except BaseException:
            await stack.__aexit__(None, None, None)
            raise

        self._exit_stack = stack
        self._session = session

    async def connect(self) -> None:
        await self._call_bg(self._connect_impl())

    async def _close_impl(self) -> None:
        if self._exit_stack is not None:
            try:
                await self._exit_stack.__aexit__(None, None, None)
            except RuntimeError:
                pass
            self._exit_stack = None
        self._session = None

    async def close(self) -> None:
        if self._bg_loop is None:
            return
        try:
            await self._call_bg(self._close_impl())
        finally:
            self._bg_loop.call_soon_threadsafe(self._bg_loop.stop)
            if self._bg_thread is not None:
                self._bg_thread.join(timeout=5.0)
            self._bg_loop = None
            self._bg_thread = None
            self._bg_ready.clear()

    async def _list_tools_impl(self) -> list[dict[str, Any]]:
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

    async def list_tools(self) -> list[dict[str, Any]]:
        return await self._call_bg(self._list_tools_impl())

    async def _execute_tool_impl(
        self,
        tool_name: str,
        arguments: dict[str, Any],
        *,
        auth_token: str | None = None,
        auth_scheme: str | None = None,
    ) -> ToolTransportResult:
        if not self._session:
            raise RuntimeError("MCP client not connected. Call connect() first.")

        mcp_log("tool start", tool=tool_name, args=dumps_clip(arguments))
        start = time.monotonic()
        meta = build_auth_meta(
            resolve_auth_token(auth_token),
            scheme=auth_scheme,
        )
        auth_trace(
            "agent_client",
            tool=tool_name,
            has_meta=meta is not None,
            scheme=auth_scheme,
        )
        try:
            result = await asyncio.wait_for(
                self._session.call_tool(tool_name, arguments, meta=meta),
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

    async def execute_tool(
        self,
        tool_name: str,
        arguments: dict[str, Any],
        *,
        auth_token: str | None = None,
        auth_scheme: str | None = None,
    ) -> ToolTransportResult:
        """调用 MCP 工具，返回传输层结果。"""
        return await self._call_bg(
            self._execute_tool_impl(
                tool_name,
                arguments,
                auth_token=auth_token,
                auth_scheme=auth_scheme,
            )
        )

    async def execute_tool_text(
        self,
        tool_name: str,
        arguments: dict[str, Any],
        *,
        auth_token: str | None = None,
        auth_scheme: str | None = None,
    ) -> str:
        return (
            await self.execute_tool(
                tool_name,
                arguments,
                auth_token=auth_token,
                auth_scheme=auth_scheme,
            )
        ).to_llm_text()


async def _demo() -> None:
    from pathlib import Path

    from hubloom.config import HubloomConfig
    from mcp_adapter.discovery import connect_full_mcp
    from mcp_adapter.gateway.catalog import format_catalog_for_prompt, load_catalog

    src = Path(__file__).resolve().parents[2]
    repo = src.parent
    cfg = HubloomConfig.from_file(str(repo / "config" / "env.yaml"))
    swagger = (cfg.mcp_swagger_url or "").strip()
    if not swagger:
        raise SystemExit("config/env.yaml 未配置 mcp.swagger_url")

    client = await connect_full_mcp(
        swagger_url=swagger,
        base_url=cfg.mcp_base_url,
        cwd=str(src),
    )
    try:
        tools = await client.list_tools()
        print(f"全量 MCP 工具数: {len(tools)}（示例前 8 个）")
        for t in tools[:8]:
            print(f"  - {t['name']}")
        print()
        catalog = await load_catalog(swagger_url=swagger, base_url=cfg.mcp_base_url)
        print(format_catalog_for_prompt(catalog))
    finally:
        await client.close()


if __name__ == "__main__":
    asyncio.run(_demo())
