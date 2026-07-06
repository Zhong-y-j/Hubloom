"""OpenAPI spec 准备管线：加载、规范化、可选过滤、解析 base URL。"""

from __future__ import annotations

from .base_url import infer_base_url, infer_base_url_from_source
from .filter import ToolFilter, count_operations, filter_openapi_spec
from .loader import load_spec
from .normalize import normalize_openapi_spec


async def prepare_openapi(
    source: str,
    *,
    base_url: str | None = None,
    tool_filter: ToolFilter | None = None,
) -> tuple[dict, str]:
    """加载 spec，规范化为 OpenAPI 3.x，可选过滤，并解析 API 根地址。"""
    raw = await load_spec(source)
    openapi = normalize_openapi_spec(raw)

    if tool_filter is not None:
        openapi = filter_openapi_spec(openapi, tool_filter)

    resolved_base_url = (
        (base_url or "").strip()
        or infer_base_url(raw)
        or infer_base_url(openapi)
        or infer_base_url_from_source(source)
        or ""
    ).rstrip("/")
    if not resolved_base_url:
        raise ValueError("无法推断 API base URL，请配置 MCP_BASE_URL")
    return openapi, resolved_base_url


async def main():
    source = "http://127.0.0.1:8888/?format=openapi"

    full, base_url = await prepare_openapi(source)
    print("=== 全量 ===")
    print("base_url:", base_url)
    print("operations:", count_operations(full))

    dic, _ = await prepare_openapi(
        source,
        tool_filter=ToolFilter(tags=["dictionary"]),
    )
    print("=== dictionary 域 ===")
    print("operations:", count_operations(dic))


if __name__ == "__main__":
    import asyncio

    asyncio.run(main())
