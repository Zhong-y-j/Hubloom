"""全量 OpenAPI MCP 后端（单一子进程，不按 tag 拆分）。"""

from __future__ import annotations

import os

from fastmcp import FastMCP

from mcp_adapter.auth import AuthPassthroughMiddleware
from mcp_adapter.server.http_client import AuthedHttpClient
from mcp_adapter.spec.pipeline import prepare_openapi


def _env(key: str, default: str = "") -> str:
    """读子进程 env（由 Hubloom runtime 的 child_env 注入），不 load_dotenv。"""
    return (os.getenv(key) or default).strip()


async def build_backend_mcp() -> FastMCP:
    """从 MCP_SWAGGER_URL 构建全量 FastMCP OpenAPI 服务。"""
    swagger_url = _env("MCP_SWAGGER_URL")
    if not swagger_url:
        raise ValueError(
            "MCP_SWAGGER_URL is not set in subprocess env "
            "(Hubloom runtime must inject mcp.swagger_url via child_env)"
        )
    base_url = _env("MCP_BASE_URL") or None

    openapi, resolved_base = await prepare_openapi(
        swagger_url,
        base_url=base_url,
        tool_filter=None,
    )

    client = AuthedHttpClient(
        base_url=resolved_base,
        trust_env=False,
        timeout=30.0,
    )

    mcp = FastMCP.from_openapi(
        openapi_spec=openapi,
        client=client,
        name="full",
        validate_output=False,
    )
    mcp.add_middleware(AuthPassthroughMiddleware())
    return mcp


async def run_backend_stdio() -> None:
    mcp = await build_backend_mcp()
    await mcp.run_stdio_async(show_banner=False)
