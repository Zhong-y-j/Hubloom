"""从 HTTP 请求头解析会话凭证（业务 Token）。"""

from __future__ import annotations

from typing import TypedDict


class ClientHeaderContext(TypedDict):
    bearer_token: str | None


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


def parse_client_headers(
    *,
    authorization: str | None = None,
    x_mcp_token: str | None = None,
) -> ClientHeaderContext:
    bearer = _clean(x_mcp_token) or _extract_bearer(authorization)
    return ClientHeaderContext(bearer_token=bearer)
