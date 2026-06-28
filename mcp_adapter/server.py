import os

import httpx
from dotenv import load_dotenv
from fastmcp import FastMCP

from http_context import StatusCapturingClient, get_last_http_response
from spec_loader import prepare_openapi

load_dotenv()

SWAGGER_URL = os.getenv(
    "MCP_SWAGGER_URL",
    "https://petstore.swagger.io/v2/swagger.json",
)
BASE_URL = os.getenv("MCP_BASE_URL", "").strip()
TOKEN = os.getenv("MCP_TOKEN", "").strip()

headers = {}
if TOKEN:
    headers["Authorization"] = f"Bearer {TOKEN}"


def _patch_openapi_tools_with_http_status() -> None:
    """在 FastMCP OpenAPI 工具返回中注入 http_status（传输层事实）。"""
    from fastmcp.server.providers.openapi.components import OpenAPITool
    from fastmcp.tools.base import ToolResult

    original_run = OpenAPITool.run

    async def run_with_http_status(self, arguments: dict):
        result = await original_run(self, arguments)
        response = get_last_http_response()
        if response is None:
            return result

        status = response.status_code
        reason = response.reason_phrase

        if isinstance(result, ToolResult):
            if result.structured_content is not None:
                structured = dict(result.structured_content)
            else:
                structured = {}
            structured["_http_status"] = status
            structured["_http_reason"] = reason
            return ToolResult(
                structured_content=structured,
                content=result.content,
                is_error=result.is_error,
            )

        return result

    OpenAPITool.run = run_with_http_status  # type: ignore[method-assign]


if __name__ == "__main__":
    import asyncio

    spec, base_url = asyncio.run(
        prepare_openapi(SWAGGER_URL, base_url=BASE_URL or None)
    )

    api_client = StatusCapturingClient(
        base_url=base_url,
        headers=headers,
        trust_env=False,
        timeout=30.0,
    )
    _patch_openapi_tools_with_http_status()
    mcp = FastMCP.from_openapi(
        openapi_spec=spec,
        client=api_client,
        name="My Swagger API",
    )
    mcp.run()
