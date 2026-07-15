"""会话 ID、路径根与本地默认值（Hubloom / HTTP 共用）。

缺省值为代码常量；进程级开关与路径由 ``HubloomConfig`` 下传，不在 import 时读 env。
"""

from __future__ import annotations

from pathlib import Path

# session.py → hubloom → src → 仓库根
_SRC_ROOT = Path(__file__).resolve().parents[1]
_REPO_ROOT = Path(__file__).resolve().parents[2]
# 包根：MCP 子进程 cwd / PYTHONPATH
SRC_ROOT = _SRC_ROOT
# 仓库根：data/、相对文档路径
REPO_ROOT = _REPO_ROOT
PROJECT_ROOT = REPO_ROOT

DEFAULT_SESSION_ID = "mem:tester_id:default"
SESSION_ID_TEMPLATE = "mem:{session_id}:default"
DEFAULT_MEMORY_DB = "data/memory.db"
DEFAULT_KB_DIR = "data/knowledge_db"

# 无 Config 时的回退（见 runtime._resolve_from_config）
ENABLE_LONG_TERM_MEMORY = False
ENABLE_RAG = False
RAG_DOCS_RAW = ""
RAG_DOC_PATHS: list[Path] = []


def format_session_id(session_key: str) -> str:
    """将短 session 键套入模板；已是 ``mem:...`` 形式则原样返回。"""
    key = (session_key or "").strip()
    if not key:
        return DEFAULT_SESSION_ID
    if key.startswith("mem:"):
        return key
    return SESSION_ID_TEMPLATE.format(session_id=key)
