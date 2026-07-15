import os

from fastmcp import FastMCP

from mcp_adapter.auth import AuthPassthroughMiddleware
from mcp_adapter.server.http_client import AuthedHttpClient
from mcp_adapter.spec.filter import ToolFilter
from mcp_adapter.spec.pipeline import prepare_openapi


def _env(key: str, default: str = "") -> str:
    """读子进程 env（由 Hubloom runtime 的 child_env 注入），不 load_dotenv。"""
    return (os.getenv(key) or default).strip()


async def build_backend_mcp(*, tag: str | None) -> FastMCP:
    """tag 即分组名，也是 FastMCP 的 server name；None 表示全量。"""
    swagger_url = _env("MCP_SWAGGER_URL")
    if not swagger_url:
        raise ValueError(
            "MCP_SWAGGER_URL is not set in subprocess env "
            "(Hubloom runtime must inject mcp.swagger_url via child_env)"
        )
    base_url = _env("MCP_BASE_URL") or None

    tool_filter = ToolFilter(tags=[tag]) if tag else None
    server_name = tag or "full"

    openapi, resolved_base = await prepare_openapi(
        swagger_url,
        base_url=base_url,
        tool_filter=tool_filter,
    )

    client = AuthedHttpClient(
        base_url=resolved_base,
        trust_env=False,
        timeout=30.0,
    )

    mcp = FastMCP.from_openapi(
        openapi_spec=openapi,
        client=client,
        name=server_name,
        validate_output=False,
    )
    mcp.add_middleware(AuthPassthroughMiddleware())
    return mcp


async def run_backend_stdio(*, tag: str | None) -> None:
    mcp = await build_backend_mcp(tag=tag)
    # stdio 子进程不打印 FastMCP 横幅；父进程关闭管道时避免噪音
    await mcp.run_stdio_async(show_banner=False)
