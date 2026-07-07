"""从 HTTP 请求头解析前端体验配置（对应 .env 字段）。"""

from __future__ import annotations

import os
from typing import TypedDict


class ClientHeaderContext(TypedDict):
    bearer_token: str | None
    openai_api_key: str | None
    openai_model: str | None
    openai_base_url: str | None
    mcp_auth_scheme: str | None
    mcp_swagger_url: str | None
    mcp_base_url: str | None


def _clean(value: str | None) -> str | None:
    text = (value or "").strip()
    return text or None


def _extract_bearer(authorization: str | None) -> str | None:
    if not authorization:
        return None
    text = authorization.strip()
    if " " in text:
        prefix, token = text.split(" ", 1)
        if prefix.lower() in ("bearer", "jwt", "token", "basic"):
            return token.strip() or None
    return text or None


def _env_or_header(header_value: str | None, env_key: str) -> str | None:
    return _clean(header_value) or _clean(os.getenv(env_key))


def parse_client_headers(
    *,
    authorization: str | None = None,
    x_openai_api_key: str | None = None,
    x_openai_model: str | None = None,
    x_openai_base_url: str | None = None,
    x_mcp_token: str | None = None,
    x_mcp_auth_scheme: str | None = None,
    x_mcp_swagger_url: str | None = None,
    x_mcp_base_url: str | None = None,
) -> ClientHeaderContext:
    """解析 chat 请求头；未传时回退进程环境变量（.env）。"""
    bearer = _clean(x_mcp_token) or _extract_bearer(authorization) or _clean(
        os.getenv("MCP_TOKEN")
    )
    return ClientHeaderContext(
        bearer_token=bearer,
        openai_api_key=_env_or_header(x_openai_api_key, "OPENAI_API_KEY"),
        openai_model=_env_or_header(x_openai_model, "OPENAI_MODEL"),
        openai_base_url=_env_or_header(x_openai_base_url, "OPENAI_BASE_URL"),
        mcp_auth_scheme=_env_or_header(x_mcp_auth_scheme, "MCP_AUTH_SCHEME")
        or "Bearer",
        mcp_swagger_url=_env_or_header(x_mcp_swagger_url, "MCP_SWAGGER_URL"),
        mcp_base_url=_env_or_header(x_mcp_base_url, "MCP_BASE_URL"),
    )
