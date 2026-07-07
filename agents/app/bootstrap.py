"""组装 CortexAgent 运行时（CLI 与 HTTP 共用）。"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Any

from agents.agent_log import cortex_log
from agents.adp.assessor import Assessor
from agents.adp.cortex_agent import CortexAgent, load_knowledge_base_from_env
from agents.app.session import (
    DEFAULT_KB_DIR,
    DEFAULT_MEMORY_DB,
    ENABLE_LONG_TERM_MEMORY,
    ENABLE_RAG,
    PROJECT_ROOT,
)
from core.factory import create_llm
from mcp_adapter.discovery import MCPBindings
from tools.registry import ToolRegistry


@dataclass
class CortexRuntime:
    """进程级共享资源；按请求创建独立 ``CortexAgent``（会话隔离）。"""

    mcp_bindings: MCPBindings | None = None
    knowledge_base: Any | None = None
    enable_mcp: bool = True
    memory_db_path: str = DEFAULT_MEMORY_DB
    api_catalog_prompt: str = ""
    _mcp_tools: list[Any] = field(default_factory=list)

    async def close(self) -> None:
        if self.mcp_bindings is not None:
            await self.mcp_bindings.client.close()
            self.mcp_bindings = None

    def create_agent(self, session_key: str) -> CortexAgent:
        """为单次对话创建 Agent（MCP 工具共享，记忆 namespace 按会话隔离）。"""
        key = (session_key or "").strip() or "tester_id"
        tools = ToolRegistry.from_tools(list(self._mcp_tools))
        agent = CortexAgent(
            create_llm(),
            tools=tools,
            assessor=Assessor(create_llm()),
            session_id=key,
            enable_long_term_memory=ENABLE_LONG_TERM_MEMORY,
            include_graph_memory=ENABLE_LONG_TERM_MEMORY,
            api_catalog_prompt=self.api_catalog_prompt,
        )
        agent.attach_readonly_tools(knowledge_base=self.knowledge_base)
        return agent


async def build_runtime_async(*, enable_mcp: bool = True) -> CortexRuntime:
    """加载 MCP / RAG，构造可复用的 CortexRuntime。"""
    runtime = CortexRuntime(enable_mcp=enable_mcp)

    if ENABLE_RAG:
        runtime.knowledge_base = await load_knowledge_base_from_env()

    if enable_mcp:
        try:
            from mcp_adapter.gateway.catalog import (
                format_catalog_for_prompt,
                load_catalog,
            )

            catalog = await load_catalog()
            runtime.api_catalog_prompt = format_catalog_for_prompt(catalog)
            cortex_log(
                "runtime api catalog loaded",
                group_count=len(catalog.list_tags()),
            )
        except Exception as exc:
            cortex_log("runtime api catalog load failed", error=str(exc))

        try:
            from mcp_adapter import load_mcp_tools

            bindings = await load_mcp_tools(
                command="uv",
                args=["run", "python", "mcp_adapter/server.py"],
                cwd=str(PROJECT_ROOT),
            )
            runtime.mcp_bindings = bindings
            runtime._mcp_tools = list(bindings.tools)
            cortex_log(
                "runtime mcp loaded",
                tool_count=len(runtime._mcp_tools),
            )
        except Exception as exc:
            cortex_log("runtime mcp load failed", error=str(exc))

    cortex_log(
        "runtime ready",
        mcp_enabled=runtime.mcp_bindings is not None,
        mcp_tools=len(runtime._mcp_tools),
        rag_enabled=ENABLE_RAG and runtime.knowledge_base is not None,
        long_term_memory=ENABLE_LONG_TERM_MEMORY,
        memory_db=runtime.memory_db_path,
        kb_dir=os.getenv("CORTEX_KB_DIR", DEFAULT_KB_DIR),
    )
    return runtime
