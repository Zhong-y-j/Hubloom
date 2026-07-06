"""拉取 Swagger/OpenAPI 文档，并在需要时把 Swagger 2.0 转为 OpenAPI 3.x。"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import httpx
from prance import BaseParser
from prance.convert import convert_spec


def _is_swagger2(spec: dict[str, Any]) -> bool:
    return str(spec.get("swagger", "")).startswith("2.")


def _is_openapi3(spec: dict[str, Any]) -> bool:
    return str(spec.get("openapi", "")).startswith("3.")


def dedupe_operation_ids(spec: dict[str, Any]) -> dict[str, Any]:
    """确保 operationId 全局唯一（DRF 等生成器常出现重复）。"""
    seen: set[str] = set()
    paths = spec.get("paths") or {}
    for path, path_item in paths.items():
        if not isinstance(path_item, dict):
            continue
        for method, operation in path_item.items():
            if method == "parameters" or not isinstance(operation, dict):
                continue
            op_id = operation.get("operationId")
            if not op_id:
                continue
            if op_id not in seen:
                seen.add(op_id)
                continue
            base = f"{op_id}_{method.lower()}"
            new_id = base
            n = 2
            while new_id in seen:
                new_id = f"{base}_{n}"
                n += 1
            operation["operationId"] = new_id
            seen.add(new_id)
    return spec


def convert_swagger2_to_openapi3(spec: dict[str, Any]) -> dict[str, Any]:
    """Swagger 2.0 → OpenAPI 3.x（通过 prance 在线转换 API）。"""
    if not _is_swagger2(spec):
        raise ValueError("spec is not Swagger 2.0")
    spec = dedupe_operation_ids(spec)
    try:
        parser = convert_spec(spec, BaseParser)
        return parser.specification
    except Exception:
        # 第三方 spec 可能仍有校验问题；转换结果可用时跳过严格校验。
        from prance.util import formats
        from prance.util.formats import parse_spec

        serialized = formats.serialize_spec(spec, content_type="application/yaml")
        from prance.convert import convert_str

        converted, _ = convert_str(serialized, content_type="application/yaml")
        return parse_spec(converted, "converted.yaml")


def normalize_openapi_spec(spec: dict[str, Any]) -> dict[str, Any]:
    """统一为 FastMCP 可用的 OpenAPI 3.x。"""
    if _is_openapi3(spec):
        return dedupe_operation_ids(spec)
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


def infer_base_url_from_source(source: str) -> str | None:
    """当 spec 未声明 servers/host 时，从 Swagger 文档 URL 推断 API 根地址。"""
    if not source.startswith(("http://", "https://")):
        return None
    parsed = urlparse(source)
    if not parsed.scheme or not parsed.netloc:
        return None
    return f"{parsed.scheme}://{parsed.netloc}".rstrip("/")


async def load_spec(source: str) -> dict[str, Any]:
    """从 URL 或本地 JSON/YAML 文件加载原始 spec。"""
    source = (source or "").strip()
    if not source:
        raise ValueError(
            "MCP_SWAGGER_URL 未配置或为空；请在 .env 中设置有效的 Swagger/OpenAPI 地址，"
            "或删除 MCP_SWAGGER_URL 以使用默认 Petstore 示例。"
        )

    path = Path(source)
    if path.is_file():
        text = path.read_text(encoding="utf-8")
        return json.loads(text)

    if not source.startswith(("http://", "https://")):
        raise ValueError(
            f"MCP_SWAGGER_URL 须为 http(s) URL 或本地文件路径，当前为: {source!r}"
        )

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
    resolved_base = (
        base_url
        or infer_base_url(raw)
        or infer_base_url(openapi)
        or infer_base_url_from_source(source)
        or ""
    ).rstrip("/")
    if not resolved_base:
        raise ValueError(
            "Cannot infer API base URL; set MCP_BASE_URL in .env"
        )
    return openapi, resolved_base
