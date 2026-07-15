"""会话 ID 与环境开关（HTTP / Agent 共用）。"""

from __future__ import annotations

import os
from pathlib import Path

from retrieval.rag_bootstrap import is_rag_enabled, parse_rag_doc_paths

# session.py → app → agents → src → 仓库根
_SRC_ROOT = Path(__file__).resolve().parents[2]
_REPO_ROOT = Path(__file__).resolve().parents[3]
# 包根：MCP 子进程 cwd / PYTHONPATH（import agents、mcp_adapter）
SRC_ROOT = _SRC_ROOT
# 仓库根：data/、.env、相对文档路径
REPO_ROOT = _REPO_ROOT
# 兼容旧名：业务相对路径仍相对仓库根
PROJECT_ROOT = REPO_ROOT
RAG_DOCS_RAW = os.getenv("CORTEX_RAG_DOCS", "").strip()
RAG_DOC_PATHS = parse_rag_doc_paths(RAG_DOCS_RAW, project_root=REPO_ROOT)
ENABLE_RAG = is_rag_enabled(RAG_DOCS_RAW)

DEFAULT_SESSION_ID = os.getenv("CORTEX_DEFAULT_SESSION_ID", "mem:tester_id:default")
SESSION_ID_TEMPLATE = os.getenv(
    "CORTEX_SESSION_ID_TEMPLATE", "mem:{session_id}:default"
)
DEFAULT_MEMORY_DB = os.getenv("CORTEX_MEMORY_DB", "data/memory.db")
DEFAULT_KB_DIR = os.getenv("CORTEX_KB_DIR", "data/knowledge_db")


def _env_flag(name: str, *, default: bool = False) -> bool:
    raw = os.getenv(name)
    if raw is None or not str(raw).strip():
        return default
    return str(raw).strip().lower() in ("1", "true", "yes", "on")


ENABLE_LONG_TERM_MEMORY = _env_flag("CORTEX_ENABLE_LONG_TERM_MEMORY", default=False)


def format_session_id(session_key: str) -> str:
    """将短 session 键套入模板；已是 ``mem:...`` 形式则原样返回。"""
    key = (session_key or "").strip()
    if not key:
        return DEFAULT_SESSION_ID
    if key.startswith("mem:"):
        return key
    return SESSION_ID_TEMPLATE.format(session_id=key)
