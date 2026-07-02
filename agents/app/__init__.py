"""Agent 运行时组装（HTTP / CLI 共用）。"""

from agents.app.bootstrap import CortexRuntime, build_runtime_async
from agents.app.session import (
    DEFAULT_SESSION_ID,
    ENABLE_LONG_TERM_MEMORY,
    ENABLE_RAG,
    RAG_DOCS_RAW,
    SESSION_ID_TEMPLATE,
    format_session_id,
)

__all__ = [
    "CortexRuntime",
    "build_runtime_async",
    "DEFAULT_SESSION_ID",
    "SESSION_ID_TEMPLATE",
    "format_session_id",
    "ENABLE_LONG_TERM_MEMORY",
    "ENABLE_RAG",
    "RAG_DOCS_RAW",
]
