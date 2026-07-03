"""将运行时 API 响应归一化为 OpenAPI/DRF 分页结构，供 MCP output schema 校验。"""

from __future__ import annotations

from typing import Any


def drf_pagination_from_envelope(payload: Any) -> dict[str, Any] | None:
    """DVAdmin 等 `{code, total, data}` → DRF `{count, results}`。"""
    if not isinstance(payload, dict):
        return None
    if "count" in payload and "results" in payload:
        return None
    if "data" not in payload:
        return None

    data = payload.get("data")
    results = data if isinstance(data, list) else []
    count = payload.get("total")
    if count is None:
        count = len(results)

    return {
        "count": count,
        "results": results,
        "next": payload.get("next"),
        "previous": payload.get("previous"),
    }
