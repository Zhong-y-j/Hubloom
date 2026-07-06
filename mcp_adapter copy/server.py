import os
import time
from typing import Any

import httpx
from dotenv import load_dotenv
from fastmcp import FastMCP

from http_context import StatusCapturingClient, get_last_http_response
from response_normalize import drf_pagination_from_envelope
from spec_loader import prepare_openapi

load_dotenv()


def _env(key: str, default: str = "") -> str:
    """读取环境变量；空字符串视为未设置。"""
    return (os.getenv(key) or default).strip()


SWAGGER_URL = _env(
    "MCP_SWAGGER_URL",
    "https://petstore.swagger.io/v2/swagger.json",
)
BASE_URL = _env("MCP_BASE_URL")
TOKEN = _env("MCP_TOKEN")
# 认证前缀：不同后端不一致（simplejwt/DVAdmin 用 JWT，OAuth2 用 Bearer）
AUTH_SCHEME = _env("MCP_AUTH_SCHEME", "Bearer")

headers = {}
if TOKEN:
    headers["Authorization"] = f"{AUTH_SCHEME} {TOKEN}" if AUTH_SCHEME else TOKEN


def _patch_openapi_tools_with_http_status() -> None:
    """在 FastMCP OpenAPI 工具返回中注入 http_status，并修正分页响应结构。"""
    import json

    from fastmcp.server.providers.openapi.components import OpenAPITool
    from fastmcp.tools.base import ToolResult
    from mcp.types import TextContent

    from log import clip_text, dumps_clip, mcp_log

    original_run = OpenAPITool.run

    def _raw_http_json() -> dict[str, Any] | list[Any] | None:
        response = get_last_http_response()
        if response is None:
            return None
        text = (response.text or "").strip()
        if not text:
            return None
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            return None

    async def run_with_http_status(self, arguments: dict):
        tool_name = getattr(self, "name", type(self).__name__)
        mcp_log("server tool start", tool=tool_name, args=dumps_clip(arguments))
        start = time.monotonic()
        try:
            result = await original_run(self, arguments)
        except Exception as exc:
            mcp_log(
                "server tool failed",
                tool=tool_name,
                error=clip_text(str(exc)),
                elapsed_ms=int((time.monotonic() - start) * 1000),
            )
            raise

        response = get_last_http_response()
        elapsed_ms = int((time.monotonic() - start) * 1000)
        fields: dict = {"tool": tool_name, "elapsed_ms": elapsed_ms}

        if response is not None:
            status = response.status_code
            reason = response.reason_phrase
            fields["http_status"] = status
            fields["http_reason"] = reason
        else:
            status = None
            reason = None

        if isinstance(result, ToolResult):
            raw_payload = _raw_http_json()
            structured = (
                dict(result.structured_content)
                if isinstance(result.structured_content, dict)
                else result.structured_content
            )
            content = list(result.content or [])
            if isinstance(raw_payload, dict):
                normalized = drf_pagination_from_envelope(raw_payload)
                if normalized is not None:
                    structured = normalized
                    raw_text = json.dumps(raw_payload, ensure_ascii=False)
                    if not any(
                        getattr(block, "text", None) == raw_text for block in content
                    ):
                        content.insert(0, TextContent(type="text", text=raw_text))

            if result.is_error:
                err_parts = []
                for block in result.content or []:
                    text = getattr(block, "text", None)
                    if text:
                        err_parts.append(text)
                fields["is_error"] = True
                fields["error"] = clip_text("\n".join(err_parts) or "ToolResult.is_error")
            elif isinstance(structured, dict) and structured:
                payload = {
                    k: v
                    for k, v in structured.items()
                    if not str(k).startswith("_http_")
                }
                fields["result"] = dumps_clip(payload if payload else structured)
            elif result.structured_content is not None:
                payload = {
                    k: v
                    for k, v in dict(result.structured_content).items()
                    if not str(k).startswith("_http_")
                }
                fields["result"] = dumps_clip(payload if payload else result.structured_content)
            elif result.content:
                texts = [
                    getattr(b, "text", str(b)) for b in (result.content or [])
                ]
                fields["result"] = clip_text("\n".join(texts))
            mcp_log("server tool done", **fields)

            if response is None:
                return result

            meta = dict(result.meta or {})
            meta["http_status"] = status
            meta["http_reason"] = reason
            return ToolResult(
                structured_content=structured,
                content=content,
                is_error=result.is_error,
                meta=meta,
            )

        mcp_log("server tool done", **fields)
        return result

    OpenAPITool.run = run_with_http_status  # type: ignore[method-assign]


if __name__ == "__main__":
    import asyncio

    if os.getenv("CORTEX_AGENT_LOG", "").lower() in ("1", "true", "yes") or os.getenv(
        "CORTEX_MCP_LOG", ""
    ).lower() in ("1", "true", "yes"):
        try:
            from observability import setup_log

            setup_log()
        except ModuleNotFoundError:
            pass

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
