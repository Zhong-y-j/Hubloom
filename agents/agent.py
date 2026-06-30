from __future__ import annotations

import asyncio
import time
from collections.abc import Callable
from typing import TYPE_CHECKING, Any, AsyncIterator, Optional


from .base import BaseAgent

from core.provider import (
    DeltaEvent,
    StreamEndEvent,
    StreamErrorEvent,
    LLMProvider,
)
from tools import ToolRegistry, ToolRunner
from .prompts import DEFAULT_SYSTEM

if TYPE_CHECKING:
    from memory.context import ContextAssembler
    from memory.memory_context import MemoryContextProvider
    from memory.store.conversation_sqlite_store import ConversationSQLitesStore
    from memory.manager import MemoryManager
    from retrieval.knowledge_base import KnowledgeBase


class CortexAgent(BaseAgent):
    """
    ReActAgent（意图澄清）：流式 LLM + MCP 工具 + 结构化 intent 输出。

    Args:
        llm:
        tools: 工具注册表
        system_prompt: 系统提示词
        max_steps: 最大步数，默认8
        allowed_tools: 允许的工具列表
        tool_max_attempts: 工具最大尝试次数，默认3
        memory_manager: 记忆管理器，默认None
        conversation_store: 历史会话存储
        session_id: 会话ID
        context_assembler: 上下文装配器
        knowledge_base: 知识库
        history_limit: 历史记录限制，默认20
    """

    def __init__(
        self,
        llm: LLMProvider,
        tools: ToolRegistry,
        *,
        system_prompt: str | None = None,  # None → prompts.build_system_prompt(tools)
        # --- 循环 ---
        max_steps: int = 8,
        allowed_tools: set[str] | None = None,
        tool_max_attempts: int = 3,
        # --- 上下文 / 记忆 ---
        memory_manager: MemoryManager | None = None,
        conversation_store: ConversationSQLitesStore | None = None,
        session_id: str | None = None,
        context_assembler: ContextAssembler | None = None,
        knowledge_base: KnowledgeBase | None = None,
        history_limit: int = 20,
    ):
        base = system_prompt.strip() if system_prompt is not None else DEFAULT_SYSTEM
        super().__init__(llm, system_prompt=base, memory_manager=memory_manager)

        self._system_prompt_str = base
        self.tools = tools
        self.max_steps = max_steps
        self.allowed_tools = allowed_tools
        self.tool_max_attempts = max(1, tool_max_attempts)

        self._conversation_store = conversation_store
        self._session_id = session_id
        self._context_assembler = context_assembler
        self._knowledge_base: Any = knowledge_base
        self._history_limit = history_limit
