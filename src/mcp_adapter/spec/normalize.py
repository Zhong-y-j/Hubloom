"""Swagger 2.0 / OpenAPI 3.x 规范化为 FastMCP 可用的 OpenAPI 3.x。"""

from __future__ import annotations
from typing import Any
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
    if _is_openapi3(spec):
        return dedupe_operation_ids(spec)
    if _is_swagger2(spec):
        return convert_swagger2_to_openapi3(spec)
    raise ValueError("不支持的 spec：需要 swagger 2.x 或 openapi 3.x")


async def main():
    from mcp_adapter.spec.loader import load_spec

    spec = await load_spec("https://api.zbx.vzerosoft.com/swagger/v1/swagger.json")
    print("raw:", spec.get("swagger") or spec.get("openapi"))

    oas = normalize_openapi_spec(spec)
    print("normalized:", oas.get("openapi"))  # 3.x
    print("paths:", len(oas.get("paths", {})))


if __name__ == "__main__":
    import asyncio

    asyncio.run(main())
