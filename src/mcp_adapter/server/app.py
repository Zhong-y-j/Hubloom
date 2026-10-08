"""全量 OpenAPI MCP 后端（单一进程：stdio 子进程或独立 HTTP 服务）。"""

from __future__ import annotations

import os

import httpx
from fastmcp import FastMCP

from mcp_adapter.auth import AuthPassthroughMiddleware
from mcp_adapter.config.models import McpServeConfig
from mcp_adapter.server.http_client import AuthedHttpClient
from mcp_adapter.spec.pipeline import prepare_openapi

# 与 WorldQuant /simulate 等长任务对齐（服务端内部轮询可达约 900s）
_DEFAULT_HTTP_TIMEOUT = 900.0


def _env(key: str, default: str = "") -> str:
    """读进程 env（stdio 由父进程注入；HTTP 独立部署时由容器 env 注入）。"""
    return (os.getenv(key) or default).strip()


def _env_float(key: str, default: float) -> float:
    raw = _env(key)
    if not raw:
        return default
    try:
        value = float(raw)
    except ValueError:
        return default
    return value if value > 0 else default


async def build_backend_mcp() -> FastMCP:
    """从 MCP_SWAGGER_URL 构建全量 FastMCP OpenAPI 服务。"""
    swagger_url = _env("MCP_SWAGGER_URL")
    if not swagger_url:
        raise ValueError(
            "MCP_SWAGGER_URL is not set "
            "(stdio: Hubloom 经 child_env 注入；HTTP: 容器/进程环境变量)"
        )
    base_url = _env("MCP_BASE_URL") or None
    http_timeout = _env_float("MCP_HTTP_TIMEOUT", _DEFAULT_HTTP_TIMEOUT)

    openapi, resolved_base = await prepare_openapi(
        swagger_url,
        base_url=base_url,
        tool_filter=None,
    )

    client = AuthedHttpClient(
        base_url=resolved_base,
        trust_env=False,
        # connect 短、read 长：仿真等接口会同步等到完成才返回
        timeout=httpx.Timeout(http_timeout, connect=30.0),
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


async def run_backend_http(config: McpServeConfig | None = None) -> None:
    """以 Streamable HTTP 独立部署（可单独打容器）。"""
    cfg = config or McpServeConfig()
    mcp = await build_backend_mcp()
    await mcp.run_http_async(
        show_banner=cfg.show_banner,
        transport=cfg.transport,
        host=cfg.host,
        port=cfg.port,
        path=cfg.path,
        log_level=cfg.log_level,
        uvicorn_config=cfg.uvicorn_config,
        stateless_http=cfg.stateless_http,
    )
