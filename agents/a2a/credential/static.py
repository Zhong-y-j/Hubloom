"""静态凭证：开发 / 联调用假 user_id + token。

正式环境再换成：读请求头验票 → 得到真实 A2 用户 ID 与 token。
"""

from __future__ import annotations

import os

from agents.a2a.credential.base import Credential

# 本地联调假身份；可用环境变量覆盖。
_STATIC_USER_ID = "a2a_dev_user"
_STATIC_TOKEN = "a2a-dev-token"


def resolve_credential() -> Credential:
    """返回当前可用的静态 Credential（入站联调入口）。"""
    user_id = (os.getenv("A2A_STATIC_USER_ID") or _STATIC_USER_ID).strip()
    token = (os.getenv("A2A_STATIC_TOKEN") or _STATIC_TOKEN).strip()
    if not user_id:
        raise ValueError("A2A static user_id is empty; set A2A_STATIC_USER_ID")
    if not token:
        raise ValueError("A2A static token is empty; set A2A_STATIC_TOKEN")
    return Credential(token=token, user_id=user_id)
