"""凭证层结果类型。"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Credential:
    """可用凭证：执行层据此透传给 MCP / 企业 API。"""

    token: str
    scheme: str = "Bearer"

    def authorization_header(self) -> str:
        return f"{self.scheme} {self.token}".strip()


@dataclass(frozen=True)
class AuthChallenge:
    """无凭证时的挑战（完整 login_link 方案以后再用）。"""

    message: str
    login_url: str | None = None
