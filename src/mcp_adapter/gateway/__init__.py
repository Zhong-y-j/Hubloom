"""网关包：仅保留 OpenAPI 分组目录（Agent 主路径不再使用按 tag 的 MCP 进程池）。"""

from mcp_adapter.gateway.catalog import (
    GatewayCatalog,
    format_catalog_for_prompt,
    load_catalog,
)

__all__ = [
    "GatewayCatalog",
    "format_catalog_for_prompt",
    "load_catalog",
]
