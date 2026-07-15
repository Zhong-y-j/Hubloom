"""凭证层（简化占位）：执行前提供 Credential，后续可换成可插拔 Provider。"""

from agents.a2a.credential.base import AuthChallenge, Credential
from agents.a2a.credential.static import resolve_credential

__all__ = [
    "AuthChallenge",
    "Credential",
    "resolve_credential",
]
