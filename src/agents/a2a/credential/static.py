"""静态凭证：开发 / 联调用假 user_id + token。

正式环境再换成：读请求头验票 → 得到真实 A2 用户 ID 与 token。
可由 ``configure_credential`` / HubloomConfig.a2a_static_token 注入，不读环境变量。
"""

from __future__ import annotations

from agents.a2a.credential.base import Credential
from agents.agent_log import a2a_log

# 本地联调假身份；可用 configure_credential 覆盖。
_STATIC_USER_ID = "a2a_dev_user"
_STATIC_TOKEN = "a2a-dev-token"

_configured_user_id: str | None = None
_configured_token: str | None = None


def configure_credential(
    *,
    user_id: str | None = None,
    token: str | None = None,
) -> None:
    """进程级注入入站静态凭证（Hubloom create 时可选调用）。"""
    global _configured_user_id, _configured_token
    uid = (user_id or "").strip()
    tok = (token or "").strip()
    _configured_user_id = uid or None
    _configured_token = tok or None


def resolve_credential(
    *,
    user_id: str | None = None,
    token: str | None = None,
) -> Credential:
    """返回当前可用的静态 Credential（入站联调入口）。"""
    uid = (
        (user_id or "").strip()
        or (_configured_user_id or "").strip()
        or _STATIC_USER_ID
    )
    tok = (
        (token or "").strip()
        or (_configured_token or "").strip()
        or _STATIC_TOKEN
    )
    if not uid:
        raise ValueError("A2A static user_id is empty")
    if not tok:
        raise ValueError(
            "A2A static token is empty "
            "(pass HubloomConfig.a2a_static_token or configure_credential)"
        )
    cred = Credential(token=tok, user_id=uid)
    a2a_log(
        "credential resolved",
        user_id=cred.user_id,
        has_token=bool(cred.token),
        scheme=cred.scheme,
    )
    return cred
