"""在 OpenAPI 已经规范化之后，按规则事先分成多个小集合"""

from __future__ import annotations
import copy
from dataclasses import dataclass
from typing import Any


@dataclass
class ToolFilter:
    """工具暴露过滤条件；各字段为 None 表示不限制。"""

    tags: list[str] | None = None
    methods: list[str] | None = None
    path_prefix: str | None = None


def _normalize_methods(methods: list[str] | None) -> set[str] | None:
    if not methods:
        return None
    return {m.lower() for m in methods}


def _operation_tags(operation: dict[str, Any]) -> set[str]:
    raw = operation.get("tags") or []
    return {str(t) for t in raw if t}


def count_operations(spec: dict[str, Any]) -> int:
    """统计 operation 数量（更接近 MCP 工具数）。"""
    n = 0
    for path_item in (spec.get("paths") or {}).values():
        if not isinstance(path_item, dict):
            continue
        for method, operation in path_item.items():
            if method == "parameters" or not isinstance(operation, dict):
                continue
            n += 1
    return n


def list_tags(spec: dict[str, Any]) -> list[str]:
    """列出 spec 里出现过的所有 tag（方便你看 Swagger 怎么分组）。"""
    seen: set[str] = set()
    for path_item in (spec.get("paths") or {}).values():
        if not isinstance(path_item, dict):
            continue
        for method, operation in path_item.items():
            if method == "parameters" or not isinstance(operation, dict):
                continue
            seen.update(_operation_tags(operation))
    return sorted(seen)


def filter_openapi_spec(
    spec: dict[str, Any],
    tool_filter: ToolFilter | None = None,
) -> dict[str, Any]:
    """按 ToolFilter 裁剪 paths，返回新 spec（不修改入参）。"""
    if tool_filter is None:
        return spec
    allowed_methods = _normalize_methods(tool_filter.methods)
    allowed_tags = set(tool_filter.tags or []) if tool_filter.tags else None
    path_prefix = (tool_filter.path_prefix or "").strip() or None
    if allowed_methods is None and allowed_tags is None and path_prefix is None:
        return spec
    out = copy.deepcopy(spec)
    paths = out.get("paths") or {}
    new_paths: dict[str, Any] = {}
    for path, path_item in paths.items():
        if not isinstance(path_item, dict):
            continue
        if path_prefix and not str(path).startswith(path_prefix):
            continue
        kept: dict[str, Any] = {}
        for method, operation in path_item.items():
            if method == "parameters":
                kept[method] = operation
                continue
            if not isinstance(operation, dict):
                continue
            if allowed_methods is not None and method.lower() not in allowed_methods:
                continue
            if allowed_tags is not None and not (
                _operation_tags(operation) & allowed_tags
            ):
                continue
            kept[method] = operation
        # 去掉只剩 parameters 的空 path
        has_operation = any(
            k != "parameters" and isinstance(v, dict) for k, v in kept.items()
        )
        if has_operation:
            new_paths[path] = kept
    out["paths"] = new_paths
    return out


def summarize_by_tag(spec: dict[str, Any]) -> dict[str, int]:
    """自动统计每个 tag 下有多少个 operation（接口操作数）。"""
    counts: dict[str, int] = {}
    for path_item in (spec.get("paths") or {}).values():
        if not isinstance(path_item, dict):
            continue
        for method, operation in path_item.items():
            if method == "parameters" or not isinstance(operation, dict):
                continue
            tags = _operation_tags(operation)
            if not tags:
                counts["_untagged"] = counts.get("_untagged", 0) + 1
                continue
            for tag in tags:
                counts[tag] = counts.get(tag, 0) + 1
    return dict(sorted(counts.items(), key=lambda x: (-x[1], x[0])))


def split_by_tag(spec: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """按 Swagger 已有 tag 自动拆成多份子 spec（物理拆分的原材料）。"""
    groups: dict[str, dict[str, Any]] = {}
    for tag in summarize_by_tag(spec):
        if tag == "_untagged":
            continue
        groups[tag] = filter_openapi_spec(spec, ToolFilter(tags=[tag]))
    return groups


async def main():
    from mcp_adapter.spec.loader import load_spec
    from mcp_adapter.spec.normalize import normalize_openapi_spec

    source = "http://127.0.0.1:8888/?format=openapi"
    raw = await load_spec(source)
    openapi = normalize_openapi_spec(raw)

    print("=== 全量 ===")
    print("paths:", len(openapi.get("paths", {})))
    print("operations:", count_operations(openapi))
    print()

    print("=== 按 tag 自动分组（每个域多少接口）===")
    summary = summarize_by_tag(openapi)
    for tag, n in summary.items():
        print(f"  {tag}: {n}")
    print()

    print("=== 示例：dictionary 域 ===")
    groups = split_by_tag(openapi)
    dic = groups.get("dictionary")
    if dic:
        print("  paths:", len(dic.get("paths", {})))
        print("  operations:", count_operations(dic))
        for path, path_item in list((dic.get("paths") or {}).items())[:3]:
            methods = [
                m.upper()
                for m, op in path_item.items()
                if m != "parameters" and isinstance(op, dict)
            ]
            print(f"    {path}  {methods}")


if __name__ == "__main__":
    import asyncio

    asyncio.run(main())
