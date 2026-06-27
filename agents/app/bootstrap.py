"""组装 ReAct / PlanExecute / Reflection / Hub（CLI 与 main 共用）。"""

from __future__ import annotations

import asyncio
import os
from pathlib import Path

from agents.hub import CortexHub, build_default_registry
from agents.plan import LLMPlanGenerator, PlanExecuteAgent, StubPlanGenerator
from agents.react import ReActAgent
from agents.reflection import ReflectionAgent
from agents.specialists import RegistryStepDelegate
from memory.context import ContextAssembler
from core import create_llm
from embedders.openai_embedder import OpenAIEmbedder
from memory.factory import create_memory_manager
from memory.store.conversation_sqlite_store import ConversationSQLitesStore
from retrieval.knowledge_base import KnowledgeBase
from tools import ToolRegistry
from tools.builtin import SearchDocumentsTool, SearchMemoryTool
from tools.runner import ToolRunner
from agents.core.agent_log import hub_log

DEFAULT_SESSION_ID = "mem:tester_id:default"
DEFAULT_MEMORY_DB = "data/memory.db"
DEFAULT_KB_DIR = "data/knowledge_db"
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent


async def build_hub_async(
    *,
    run_reflection: bool = True,
    session_id: str = DEFAULT_SESSION_ID,
    memory_db_path: str = DEFAULT_MEMORY_DB,
    kb_persist_dir: str = DEFAULT_KB_DIR,
    max_revision_rounds: int | None = None,
    enable_mcp: bool = True,
) -> CortexHub:
    """构造可运行的 CortexHub 实例（异步加载 MCP 工具）。"""
    llm = create_llm()
    conversation_store = ConversationSQLitesStore(memory_db_path)
    kb = KnowledgeBase(embedder=OpenAIEmbedder(), persist_dir=kb_persist_dir)
    memory_manager = create_memory_manager(namespace=session_id)

    bindings = None
    mcp_registry = ToolRegistry()
    if enable_mcp:
        try:
            from mcp_adapter import load_mcp_tools

            bindings = await load_mcp_tools(
                command="uv",
                args=["run", "python", "mcp_adapter/server.py"],
                cwd=str(PROJECT_ROOT),
            )
            mcp_registry = ToolRegistry.from_tools(bindings.tools)
            hub_log("mcp loaded", tool_count=len(bindings.tools))
        except Exception as exc:
            hub_log("mcp load failed; fallback to agent registry", error=str(exc))

    react_tool_list: list = [
        SearchDocumentsTool(kb),
        SearchMemoryTool(memory_manager),
    ]
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
        consolidate_memory=True,
        allowed_tools={"search_documents", "search_memory"},
    )

    if bindings is not None:
        fallback = StubPlanGenerator(tools=mcp_registry)
        plan_execute = PlanExecuteAgent(
            llm,
            plan_generator=LLMPlanGenerator(
                llm, tools=mcp_registry, fallback=fallback
            ),
            tool_runner=ToolRunner(mcp_registry),
        )
    else:
        registry = build_default_registry()
        plan_execute = PlanExecuteAgent(
            llm,
            plan_generator=LLMPlanGenerator(llm, registry=registry),
            registry=registry,
            step_delegate=RegistryStepDelegate(llm),
        )

    reflection = ReflectionAgent(llm) if run_reflection else None
    if max_revision_rounds is None:
        max_revision_rounds = int(os.getenv("HUB_MAX_REVISION_ROUNDS", "1"))
    hub_log(
        "build_hub",
        session_id=session_id,
        memory_db=memory_db_path,
        kb_dir=kb_persist_dir,
        run_reflection=run_reflection,
        max_revision_rounds=max_revision_rounds,
        mcp_enabled=bindings is not None,
    )
    return CortexHub(
        react,
        plan_execute,
        reflection,
        run_reflection=run_reflection,
        stream_plan_separately=True,
        max_revision_rounds=max_revision_rounds,
        mcp_bindings=bindings,
    )


def build_hub(
    *,
    run_reflection: bool = True,
    session_id: str = DEFAULT_SESSION_ID,
    memory_db_path: str = DEFAULT_MEMORY_DB,
    kb_persist_dir: str = DEFAULT_KB_DIR,
    max_revision_rounds: int | None = None,
    enable_mcp: bool = True,
) -> CortexHub:
    """同步构造 CortexHub（内部 asyncio.run 加载 MCP）。"""
    return asyncio.run(
        build_hub_async(
            run_reflection=run_reflection,
            session_id=session_id,
            memory_db_path=memory_db_path,
            kb_persist_dir=kb_persist_dir,
            max_revision_rounds=max_revision_rounds,
            enable_mcp=enable_mcp,
        )
    )
