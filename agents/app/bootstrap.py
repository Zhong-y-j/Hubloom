"""组装 ReAct / PlanExecute / Reflection / Hub（CLI 与 main 共用）。"""

from __future__ import annotations

import os

from agents.hub import CortexHub, build_default_registry
from agents.plan import LLMPlanGenerator, PlanExecuteAgent
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
from agents.core.agent_log import hub_log

DEFAULT_SESSION_ID = "mem:tester_id:default"
DEFAULT_MEMORY_DB = "data/memory.db"
DEFAULT_KB_DIR = "data/knowledge_db"


def build_hub(
    *,
    run_reflection: bool = True,
    session_id: str = DEFAULT_SESSION_ID,
    memory_db_path: str = DEFAULT_MEMORY_DB,
    kb_persist_dir: str = DEFAULT_KB_DIR,
    max_revision_rounds: int | None = None,
) -> CortexHub:
    """构造可运行的 CortexHub 实例。"""
    llm = create_llm()
    conversation_store = ConversationSQLitesStore(memory_db_path)
    kb = KnowledgeBase(embedder=OpenAIEmbedder(), persist_dir=kb_persist_dir)
    memory_manager = create_memory_manager(namespace=session_id)
    tools = ToolRegistry.from_tools(
        [
            SearchDocumentsTool(kb),
            SearchMemoryTool(memory_manager),
        ]
    )
    react = ReActAgent(
        llm,
        tools,
        memory_manager=memory_manager,
        conversation_store=conversation_store,
        session_id=session_id,
        context_assembler=ContextAssembler(),
        knowledge_base=kb,
        consolidate_memory=True,
    )
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
    )
    return CortexHub(
        react,
        plan_execute,
        reflection,
        run_reflection=run_reflection,
        stream_plan_separately=True,
        max_revision_rounds=max_revision_rounds,
    )
