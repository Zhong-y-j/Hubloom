"""从 HubloomConfig / 原始 mcp 段构造 ``McpEndpoint`` 列表。"""

from __future__ import annotations

from typing import Any, Sequence

from mcp_adapter.config.models import McpEndpoint, McpServeConfig


def endpoints_from_config(cfg: Any) -> list[McpEndpoint]:
    """把 ``HubloomConfig`` 的 mcp 字段转成可连接的 endpoint 列表。

    - 主路：``id=primary``，由 ``mcp_transport`` / swagger 或 url 决定。
    - ``mcp_remotes``：每项 ``id`` + ``url``（及可选 headers）。
    """
    transport = (getattr(cfg, "mcp_transport", None) or "stdio").strip().lower()
    endpoints: list[McpEndpoint] = []

    child_env: dict[str, str] = {}
    scheme = getattr(cfg, "mcp_auth_scheme", None)
    if scheme:
        child_env["MCP_AUTH_SCHEME"] = str(scheme).strip()
    # 业务 Token 仅由请求透传，不从配置注入 MCP_TOKEN

    if transport == "http":
        url = (getattr(cfg, "mcp_url", None) or "").strip()
        if not url:
            raise ValueError("mcp.transport=http 时需要 mcp.url")
        endpoints.append(
            McpEndpoint(id="primary", transport="http", url=url, env=child_env)
        )
    else:
        swagger = (getattr(cfg, "mcp_swagger_url", None) or "").strip()
        if not swagger:
            raise ValueError("mcp.transport=stdio 时需要 mcp.swagger_url")
        endpoints.append(
            McpEndpoint(
                id="primary",
                transport="stdio",
                swagger_url=swagger,
                base_url=getattr(cfg, "mcp_base_url", None),
                env=child_env,
            )
        )

    remotes: Sequence[dict[str, Any]] = getattr(cfg, "mcp_remotes", None) or []
    for i, raw in enumerate(remotes):
        rid = str(raw.get("id") or "").strip() or f"remote{i}"
        rurl = str(raw.get("url") or "").strip()
        if not rurl:
            raise ValueError(f"mcp.remotes[{i}] 缺少 url")
        headers = raw.get("headers") if isinstance(raw.get("headers"), dict) else {}
        endpoints.append(
            McpEndpoint(
                id=rid,
                transport="http",
                url=rurl,
                headers={str(k): str(v) for k, v in headers.items()},
            )
        )
    return endpoints


def serve_config_from_hubloom(cfg: Any) -> McpServeConfig:
    """独立 HTTP 服务参数（缺省与 worker --http 一致）。"""
    return McpServeConfig(
        host=(getattr(cfg, "mcp_serve_host", None) or "0.0.0.0").strip(),
        port=int(getattr(cfg, "mcp_serve_port", None) or 8001),
        path=(getattr(cfg, "mcp_serve_path", None) or "/mcp").strip() or "/mcp",
    )
