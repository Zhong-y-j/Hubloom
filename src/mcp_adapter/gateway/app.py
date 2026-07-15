"""网关 MCP：stdio 入口（旧链路；Agent 主路径已改为原生元工具 → 全量 worker）。

独立调试仍可运行::

    PYTHONPATH=src MCP_SWAGGER_URL=... uv run python mcp_adapter/server.py
"""

from __future__ import annotations

import os

from fastmcp import FastMCP

from mcp_adapter.gateway.catalog import load_catalog
from mcp_adapter.auth import AuthPassthroughMiddleware
from mcp_adapter.gateway.meta_tools import register_meta_tools
from mcp_adapter.gateway.pool import BackendPool
from mcp_adapter.gateway.router import BackendRouter


def _child_swagger_url() -> str:
    """子进程 env 由 Hubloom ``_mcp_child_env`` 注入。"""
    url = (os.getenv("MCP_SWAGGER_URL") or "").strip()
    if not url:
        raise ValueError(
            "MCP_SWAGGER_URL is not set in subprocess env "
            "(Hubloom runtime must inject mcp.swagger_url via child_env)"
        )
    return url


def build_gateway_mcp(catalog, router: BackendRouter) -> FastMCP:
    mcp = FastMCP(
        name="Gateway",
        instructions=(
            "这是 API 网关。流程：list_tools(tag) → "
            "call_tool(tag, tool_name, arguments)。"
            "tag 列表见 Agent system prompt 中的 API 分组目录。"
        ),
    )
    register_meta_tools(mcp, router)
    mcp.add_middleware(AuthPassthroughMiddleware())
    return mcp


async def run_gateway() -> None:
    catalog = await load_catalog(swagger_url=_child_swagger_url())
    pool = BackendPool(catalog)
    router = BackendRouter(catalog, pool=pool)

    try:
        await pool.prewarm()
        mcp = build_gateway_mcp(catalog, router)
        await mcp.run_stdio_async()
    finally:
        await pool.close()


async def debug_list_meta_tools() -> None:
    """本地调试：打印网关元工具列表（不要和 run_gateway 混用 stdio）。"""
    catalog = await load_catalog(swagger_url=_child_swagger_url())
    router = BackendRouter(catalog)
    mcp = build_gateway_mcp(catalog, router)
    tools = await mcp.list_tools()
    print(f"网关元工具数: {len(tools)}")
    for tool in tools:
        print(f"  - {tool.name}: {(tool.description or '')[:60]}")
    await router.close()


if __name__ == "__main__":
    import asyncio

    asyncio.run(debug_list_meta_tools())
