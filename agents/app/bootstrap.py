"""组装 ReAct / Hub（CLI 与 HTTP 共用）。"""

from __future__ import annotations

import asyncio
import os
from pathlib import Path

from agents.hub import CortexHub
from agents.react import ReActAgent
from memory.context import ContextAssembler
from core import create_llm
from memory.factory import create_memory_manager
from memory.store.conversation_sqlite_store import ConversationSQLitesStore
from retrieval.rag_bootstrap import (
    create_knowledge_base,
    ingest_rag_sources,
    is_rag_enabled,
    parse_rag_doc_paths,
)
from tools import ToolRegistry
from tools.builtin import SearchDocumentsTool, SearchMemoryTool
from agents.core.agent_log import hub_log

DEFAULT_SESSION_ID = os.getenv("CORTEX_DEFAULT_SESSION_ID", "mem:tester_id:default")
DEFAULT_MEMORY_DB = os.getenv("CORTEX_MEMORY_DB", "data/memory.db")
DEFAULT_KB_DIR = os.getenv("CORTEX_KB_DIR", "data/knowledge_db")
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
RAG_DOCS_RAW = os.getenv("CORTEX_RAG_DOCS", "").strip()
RAG_DOC_PATHS = parse_rag_doc_paths(RAG_DOCS_RAW, project_root=PROJECT_ROOT)
ENABLE_RAG = is_rag_enabled(RAG_DOCS_RAW)
SESSION_ID_TEMPLATE = os.getenv(
    "CORTEX_SESSION_ID_TEMPLATE", "mem:{session_id}:default"
)


def _env_flag(name: str, *, default: bool = False) -> bool:
    raw = os.getenv(name)
    if raw is None or not str(raw).strip():
        return default
    return str(raw).strip().lower() in ("1", "true", "yes", "on")


ENABLE_LONG_TERM_MEMORY = _env_flag("CORTEX_ENABLE_LONG_TERM_MEMORY", default=False)


def format_session_id(session_key: str) -> str:
    """将短 session 键套入模板；已是 ``mem:...`` 形式则原样返回。"""
    key = session_key.strip()
    if not key:
        return DEFAULT_SESSION_ID
    if key.startswith("mem:"):
        return key
    return SESSION_ID_TEMPLATE.format(session_id=key)


async def build_hub_async(
    *,
    session_id: str = DEFAULT_SESSION_ID,
    memory_db_path: str = DEFAULT_MEMORY_DB,
    kb_persist_dir: str = DEFAULT_KB_DIR,
    enable_mcp: bool = True,
) -> CortexHub:
    """构造可运行的 CortexHub 实例（异步加载 MCP 工具）。"""
    llm = create_llm()
    conversation_store = ConversationSQLitesStore(memory_db_path)
    kb = None
    if ENABLE_RAG:
        kb = create_knowledge_base(persist_dir=kb_persist_dir)
        try:
            indexed = await ingest_rag_sources(kb, RAG_DOC_PATHS)
            hub_log(
                "rag ready",
                indexed=indexed,
                doc_paths=len(RAG_DOC_PATHS),
                kb_dir=kb_persist_dir,
            )
        except Exception as exc:
            hub_log("rag ingest failed", error=str(exc))
    memory_manager = create_memory_manager(
        namespace=session_id,
        db_path=memory_db_path,
        vector_backend="qdrant" if ENABLE_LONG_TERM_MEMORY else "none",
        graph_backend="neo4j" if ENABLE_LONG_TERM_MEMORY else "none",
    )

    bindings = None
    if enable_mcp:
        try:
            from mcp_adapter import load_mcp_tools

            bindings = await load_mcp_tools(
                command="uv",
                args=["run", "python", "mcp_adapter/server.py"],
                cwd=str(PROJECT_ROOT),
            )
            hub_log("mcp loaded", tool_count=len(bindings.tools))
        except Exception as exc:
            hub_log("mcp load failed", error=str(exc))

    react_tool_list: list = []
    if ENABLE_RAG and kb is not None:
        react_tool_list.append(SearchDocumentsTool(kb))
    if ENABLE_LONG_TERM_MEMORY:
        react_tool_list.append(SearchMemoryTool(memory_manager))
    if bindings is not None:
        react_tool_list.extend(bindings.tools)
    react_tools = ToolRegistry.from_tools(react_tool_list)

    react = ReActAgent(
        llm,
        react_tools,
        memory_manager=memory_manager,
        conversation_store=conversation_store,
        session_id=session_id,
        context_assembler=ContextAssembler(),
        knowledge_base=kb,
        consolidate_memory=ENABLE_LONG_TERM_MEMORY,
    )

    hub_log(
        "build_hub",
        session_id=session_id,
        memory_db=memory_db_path,
        kb_dir=kb_persist_dir,
        mcp_enabled=bindings is not None,
        long_term_memory=ENABLE_LONG_TERM_MEMORY,
        rag_enabled=ENABLE_RAG,
        rag_doc_paths=len(RAG_DOC_PATHS),
    )
    return CortexHub(react, mcp_bindings=bindings)


def build_hub(
    *,
    session_id: str = DEFAULT_SESSION_ID,
    memory_db_path: str = DEFAULT_MEMORY_DB,
    kb_persist_dir: str = DEFAULT_KB_DIR,
    enable_mcp: bool = True,
) -> CortexHub:
    """同步构造 CortexHub（内部 asyncio.run 加载 MCP）。"""
    return asyncio.run(
        build_hub_async(
            session_id=session_id,
            memory_db_path=memory_db_path,
            kb_persist_dir=kb_persist_dir,
            enable_mcp=enable_mcp,
        )
    )
