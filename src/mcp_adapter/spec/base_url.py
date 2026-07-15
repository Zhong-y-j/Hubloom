"""从 OpenAPI spec 或文档来源推断 API 根地址。"""

from __future__ import annotations

from typing import Any
from urllib.parse import urlparse


def _is_swagger2(spec: dict[str, Any]) -> bool:
    return str(spec.get("swagger", "")).startswith("2.")


def infer_base_url(spec: dict[str, Any]) -> str | None:
    """从 spec 的 host/basePath 或 servers 推断根地址。"""
    if _is_swagger2(spec):
        host = spec.get("host")
        if not host:
            return None
        scheme = (spec.get("schemes") or ["https"])[0]
        base_path = spec.get("basePath") or ""
        return f"{scheme}://{host}{base_path}".rstrip("/")

    servers = spec.get("servers") or []
    if not servers:
        return None

    url = str(servers[0].get("url", "")).strip()
    if not url:
        return None
    if url.startswith(("http://", "https://")):
        return url.rstrip("/")
    return None


def infer_base_url_from_source(source: str) -> str | None:
    """spec 未声明 servers/host 时，从 Swagger 文档 URL 推断。"""
    if not source.startswith(("http://", "https://")):
        return None
    parsed = urlparse(source)
    if not parsed.scheme or not parsed.netloc:
        return None
    return f"{parsed.scheme}://{parsed.netloc}".rstrip("/")


async def main():
    from mcp_adapter.spec.loader import load_spec
    from mcp_adapter.spec.normalize import normalize_openapi_spec

    source = "http://127.0.0.1:8888/?format=openapi"
    raw = await load_spec(source)
    oas = normalize_openapi_spec(raw)

    print("from raw:", infer_base_url(raw))
    print("from oas:", infer_base_url(oas))
    print("from source:", infer_base_url_from_source(source))


if __name__ == "__main__":
    import asyncio

    asyncio.run(main())
