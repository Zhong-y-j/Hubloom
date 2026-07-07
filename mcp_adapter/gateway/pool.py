"""后端 worker 进程池：懒启动、连接缓存、可配置预热。

所有 worker stdio 客户端运行在独立后台事件循环中，避免与网关 MCP
stdio 服务争用同一 asyncio 循环导致嵌套调用死锁。
"""

from __future__ import annotations

import asyncio
import os
import threading
from contextlib import AsyncExitStack
from pathlib import Path
from typing import Any

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from mcp_adapter.auth import auth_trace, build_auth_meta
from mcp_adapter.gateway.catalog import GatewayCatalog

PROJECT_ROOT = Path(__file__).resolve().parents[2]

# ===== 可配置：预热（空列表 = 不预热，全靠懒加载）=====
PREWARM_TAGS: list[str] = []
# 示例：PREWARM_TAGS = ["user", "dictionary"]

PREWARM_CONCURRENCY = 4
STARTUP_TIMEOUT = 120.0
DEFAULT_TIMEOUT = 60.0
# ======================================================


def build_subprocess_env() -> dict[str, str]:
    merged = dict(os.environ)
    root = str(PROJECT_ROOT)
    existing = merged.get("PYTHONPATH", "")
    parts = [p for p in existing.split(os.pathsep) if p]
    if root not in parts:
        parts.insert(0, root)
    merged["PYTHONPATH"] = os.pathsep.join(parts)
    return merged


def worker_server_params(tag: str) -> StdioServerParameters:
    return StdioServerParameters(
        command="uv",
        args=["run", "python", "-m", "mcp_adapter.server.worker", tag],
        env=build_subprocess_env(),
        cwd=str(PROJECT_ROOT),
    )


def _tool_to_dict(tool: Any) -> dict[str, Any]:
    schema = getattr(tool, "inputSchema", None) or getattr(tool, "input_schema", None)
    if hasattr(schema, "model_dump"):
        schema = schema.model_dump(by_alias=True, exclude_none=True)
    elif schema is not None and not isinstance(schema, dict):
        schema = dict(schema)
    return {
        "name": tool.name,
        "description": tool.description or "",
        "parameters": schema or {"type": "object", "properties": {}},
    }


class BackendPool:
    """管理各 tag 对应 worker 子进程的 MCP 会话。"""

    def __init__(
        self,
        catalog: GatewayCatalog,
        *,
        timeout: float = DEFAULT_TIMEOUT,
        prewarm_tags: list[str] | None = None,
    ) -> None:
        self._catalog = catalog
        self._timeout = timeout
        self._prewarm_tags = (
            list(prewarm_tags) if prewarm_tags is not None else list(PREWARM_TAGS)
        )
        self._sessions: dict[str, ClientSession] = {}
        self._stacks: dict[str, AsyncExitStack] = {}
        self._locks: dict[str, asyncio.Lock] = {}
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
            name="mcp-backend-pool",
            daemon=True,
        )
        self._bg_thread.start()
        self._bg_ready.wait()
        assert self._bg_loop is not None
        return self._bg_loop

    async def _call_bg(self, coro: Any) -> Any:
        loop = self._ensure_bg_loop()
        return await asyncio.wrap_future(asyncio.run_coroutine_threadsafe(coro, loop))

    def _ensure_tag(self, tag: str) -> None:
        if tag not in self._catalog.groups:
            raise ValueError(f"未知分组 tag: {tag!r}")

    def _lock_for(self, tag: str) -> asyncio.Lock:
        if tag not in self._locks:
            self._locks[tag] = asyncio.Lock()
        return self._locks[tag]

    async def _get_session(self, tag: str) -> ClientSession:
        """在后台循环中获取 tag 对应后端会话（无则 spawn worker）。"""
        self._ensure_tag(tag)
        if tag in self._sessions:
            return self._sessions[tag]

        async with self._lock_for(tag):
            if tag in self._sessions:
                return self._sessions[tag]

            stack = AsyncExitStack()
            await stack.__aenter__()
            try:
                read, write = await stack.enter_async_context(
                    stdio_client(worker_server_params(tag))
                )
                session = await stack.enter_async_context(ClientSession(read, write))
                await asyncio.wait_for(session.initialize(), timeout=STARTUP_TIMEOUT)
            except BaseException:
                await stack.__aexit__(None, None, None)
                raise

            self._stacks[tag] = stack
            self._sessions[tag] = session
            return session

    async def _list_tools_impl(self, tag: str) -> list[dict[str, Any]]:
        session = await self._get_session(tag)
        result = await asyncio.wait_for(session.list_tools(), timeout=self._timeout)
        return [_tool_to_dict(tool) for tool in result.tools]

    async def _call_tool_impl(
        self,
        tag: str,
        tool_name: str,
        arguments: dict[str, Any] | None = None,
        *,
        auth_token: str | None = None,
        auth_scheme: str | None = None,
    ) -> Any:
        session = await self._get_session(tag)
        meta = build_auth_meta(auth_token, scheme=auth_scheme)
        auth_trace(
            "pool_forward",
            tag=tag,
            tool_name=tool_name,
            has_meta=meta is not None,
            scheme=auth_scheme,
        )
        return await asyncio.wait_for(
            session.call_tool(tool_name, arguments or {}, meta=meta),
            timeout=self._timeout,
        )

    async def list_tools(self, tag: str) -> list[dict[str, Any]]:
        return await self._call_bg(self._list_tools_impl(tag))

    async def call_tool(
        self,
        tag: str,
        tool_name: str,
        arguments: dict[str, Any] | None = None,
        *,
        auth_token: str | None = None,
        auth_scheme: str | None = None,
    ) -> Any:
        return await self._call_bg(
            self._call_tool_impl(
                tag,
                tool_name,
                arguments,
                auth_token=auth_token,
                auth_scheme=auth_scheme,
            )
        )

    async def _prewarm_impl(self, tags: list[str] | None = None) -> None:
        wanted = tags if tags is not None else self._prewarm_tags
        if not wanted:
            return

        valid = [t for t in wanted if t in self._catalog.groups]
        if not valid:
            return

        sem = asyncio.Semaphore(PREWARM_CONCURRENCY)

        async def _one(tag: str) -> None:
            async with sem:
                await self._get_session(tag)

        await asyncio.gather(*[_one(tag) for tag in valid])

    async def prewarm(self, tags: list[str] | None = None) -> None:
        """预热指定 tag；默认使用 PREWARM_TAGS。"""
        await self._call_bg(self._prewarm_impl(tags))

    def running_tags(self) -> list[str]:
        if self._bg_loop is None:
            return []
        fut = asyncio.run_coroutine_threadsafe(self._running_tags_impl(), self._bg_loop)
        return fut.result(timeout=5.0)

    async def _running_tags_impl(self) -> list[str]:
        return sorted(self._sessions.keys())

    async def _close_impl(self) -> None:
        for tag in list(self._stacks.keys()):
            try:
                await self._stacks[tag].__aexit__(None, None, None)
            except RuntimeError:
                pass
        self._stacks.clear()
        self._sessions.clear()
        self._locks.clear()

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

    async def __aenter__(self) -> BackendPool:
        await self.prewarm()
        return self

    async def __aexit__(self, *args: object) -> None:
        await self.close()
