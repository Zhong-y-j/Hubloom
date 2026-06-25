"""拉取 Swagger/OpenAPI 文档，并在需要时把 Swagger 2.0 转为 OpenAPI 3.x。"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import httpx
from prance import BaseParser
from prance.convert import convert_spec


def _is_swagger2(spec: dict[str, Any]) -> bool:
    return str(spec.get("swagger", "")).startswith("2.")


def _is_openapi3(spec: dict[str, Any]) -> bool:
    return str(spec.get("openapi", "")).startswith("3.")


def convert_swagger2_to_openapi3(spec: dict[str, Any]) -> dict[str, Any]:
    """Swagger 2.0 → OpenAPI 3.x（通过 prance 在线转换 API）。"""
    if not _is_swagger2(spec):
        raise ValueError("spec is not Swagger 2.0")
    parser = convert_spec(spec, BaseParser)
    return parser.specification


def normalize_openapi_spec(spec: dict[str, Any]) -> dict[str, Any]:
    """统一为 FastMCP 可用的 OpenAPI 3.x。"""
    if _is_openapi3(spec):
        return spec
    if _is_swagger2(spec):
        return convert_swagger2_to_openapi3(spec)
    raise ValueError(
        "Unsupported API spec: expected 'swagger' 2.x or 'openapi' 3.x field"
    )


def infer_base_url(spec: dict[str, Any]) -> str | None:
    """从 spec 推断 API 根地址。"""
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


async def load_spec(source: str) -> dict[str, Any]:
    """从 URL 或本地 JSON/YAML 文件加载原始 spec。"""
    path = Path(source)
    if path.is_file():
        text = path.read_text(encoding="utf-8")
        return json.loads(text)

    async with httpx.AsyncClient(trust_env=False, timeout=30.0) as client:
        response = await client.get(source)
        response.raise_for_status()
        return response.json()


async def prepare_openapi(
    source: str,
    *,
    base_url: str | None = None,
) -> tuple[dict[str, Any], str]:
    """加载 spec，必要时转换，并解析 base URL。"""
    raw = await load_spec(source)
    openapi = normalize_openapi_spec(raw)
    resolved_base = (base_url or infer_base_url(raw) or infer_base_url(openapi) or "").rstrip("/")
    if not resolved_base:
        raise ValueError(
            "Cannot infer API base URL; set BASE_URL in mcp/server.py"
        )
    return openapi, resolved_base
