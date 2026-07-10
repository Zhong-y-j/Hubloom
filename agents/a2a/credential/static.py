"""静态凭证：开发 / 联调用，直接返回程序内配置的 token。

正式环境再替换为读请求头、login_link、OAuth 等 Provider。
"""

from __future__ import annotations

import os

from agents.a2a.credential.base import Credential

# 本地联调可直接改这里；也可用环境变量 A2A_STATIC_TOKEN 覆盖。
_STATIC_TOKEN = "replace-me-with-a-dev-token"


def resolve_credential() -> Credential:
    """返回当前可用的静态 Credential（简化凭证层入口）。"""
    # token = (os.getenv("A2A_STATIC_TOKEN") or _STATIC_TOKEN).strip()
    token = _STATIC_TOKEN.strip()
    if not token:
        raise ValueError(
            "A2A static token is empty; set A2A_STATIC_TOKEN or _STATIC_TOKEN"
        )
    return Credential(token=token)
