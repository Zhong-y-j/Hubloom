"""MCP Adapter 侧连接配置（与 HubloomRuntime / env.yaml 解耦）。"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

Transport = Literal["stdio", "http"]


@dataclass(frozen=True)
class McpEndpoint:
    """一路 MCP Server 的连接描述。

    - ``transport=stdio``：本地拉起 OpenAPI worker（需 ``swagger_url``）。
    - ``transport=http``：连接已部署的 MCP（Streamable HTTP，需 ``url``）。
    """

    id: str
    transport: Transport = "stdio"
    swagger_url: str | None = None
    base_url: str | None = None
    url: str | None = None
    headers: dict[str, str] = field(default_factory=dict)
    env: dict[str, str] = field(default_factory=dict)
    timeout: float = 120.0

    def __post_init__(self) -> None:
        key = (self.id or "").strip()
        if not key:
            raise ValueError("McpEndpoint.id 不能为空")
        if self.transport == "stdio":
            if not (self.swagger_url or "").strip():
                raise ValueError(f"endpoint {key!r}: stdio 需要 swagger_url")
        elif self.transport == "http":
            if not (self.url or "").strip():
                raise ValueError(f"endpoint {key!r}: http 需要 url")
        else:
            raise ValueError(f"endpoint {key!r}: 未知 transport {self.transport!r}")


@dataclass(frozen=True)
class McpServeConfig:
    """独立 HTTP MCP 服务启动参数（容器入口用）。"""

    host: str = "0.0.0.0"
    port: int = 8001
    path: str = "/mcp"
    transport: Literal["http", "streamable-http", "sse"] = "http"
    stateless_http: bool = True
    show_banner: bool = False
    log_level: str | None = None
    uvicorn_config: dict[str, Any] | None = None
