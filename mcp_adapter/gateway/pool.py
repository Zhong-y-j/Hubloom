"""后端 worker 进程池：懒启动、连接缓存、可配置预热。"""

from __future__ import annotations

import asyncio
import os
from contextlib import AsyncExitStack
from pathlib import Path
from typing import Any

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from mcp_adapter.gateway.catalog import GatewayCatalog

PROJECT_ROOT = Path(__file__).resolve().parents[2]

# ===== 可配置：预热（空列表 = 不预热，全靠懒加载）=====
PREWARM_TAGS: list[str] = []
# 示例：PREWARM_TAGS = ["user", "dictionary"]

PREWARM_CONCURRENCY = 4
DEFAULT_TIMEOUT = 30.0
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

    def _ensure_tag(self, tag: str) -> None:
        if tag not in self._catalog.groups:
            raise ValueError(f"未知分组 tag: {tag!r}")

    def _lock_for(self, tag: str) -> asyncio.Lock:
        if tag not in self._locks:
            self._locks[tag] = asyncio.Lock()
        return self._locks[tag]

    async def get_session(self, tag: str) -> ClientSession:
        """获取 tag 对应后端会话（无则 spawn worker）。"""
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
                await asyncio.wait_for(session.initialize(), timeout=self._timeout)
            except BaseException:
                await stack.__aexit__(None, None, None)
                raise

            self._stacks[tag] = stack
            self._sessions[tag] = session
            return session

    async def list_tools(self, tag: str) -> list[dict[str, Any]]:
        session = await self.get_session(tag)
        result = await asyncio.wait_for(session.list_tools(), timeout=self._timeout)
        return [_tool_to_dict(tool) for tool in result.tools]

    async def call_tool(
        self,
        tag: str,
        tool_name: str,
        arguments: dict[str, Any] | None = None,
    ) -> Any:
        session = await self.get_session(tag)
        return await asyncio.wait_for(
            session.call_tool(tool_name, arguments or {}),
            timeout=self._timeout,
        )

    async def prewarm(self, tags: list[str] | None = None) -> None:
        """预热指定 tag；默认使用 PREWARM_TAGS。"""
        wanted = tags if tags is not None else self._prewarm_tags
        if not wanted:
            return

        valid = [t for t in wanted if t in self._catalog.groups]
        if not valid:
            return

        sem = asyncio.Semaphore(PREWARM_CONCURRENCY)

        async def _one(tag: str) -> None:
            async with sem:
                await self.get_session(tag)

        await asyncio.gather(*[_one(tag) for tag in valid])

    def running_tags(self) -> list[str]:
        return sorted(self._sessions.keys())

    async def close(self) -> None:
        for tag in list(self._stacks.keys()):
            await self._stacks[tag].__aexit__(None, None, None)
        self._stacks.clear()
        self._sessions.clear()
        self._locks.clear()

    async def __aenter__(self) -> BackendPool:
        await self.prewarm()
        return self

    async def __aexit__(self, *args: object) -> None:
        await self.close()
