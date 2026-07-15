"""组装 Hubloom 运行时（门面 create / HTTP / A2A 共用）。"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Any

from agents.agent_log import cortex_log
from agents.adp.assessor import Assessor
from agents.adp.cortex_agent import CortexAgent, load_knowledge_base_from_env
from agents.api.request_context import (
    get_openai_api_key,
    get_openai_base_url,
    get_openai_model,
)
from core.factory import create_llm
from hubloom.config import HubloomConfig
from hubloom.session import (
    DEFAULT_KB_DIR,
    DEFAULT_MEMORY_DB,
    ENABLE_LONG_TERM_MEMORY,
    ENABLE_RAG,
    SRC_ROOT,
)
from mcp_adapter.discovery import MCPBindings
from tools.registry import ToolRegistry


def _first_str(*values: str | None) -> str | None:
    for value in values:
        text = (value or "").strip()
        if text:
            return text
    return None


@dataclass
class CortexRuntime:
    """进程/实例级共享资源；按会话创建独立 ``CortexAgent``。"""

    mcp_bindings: MCPBindings | None = None
    knowledge_base: Any | None = None
    enable_mcp: bool = True
    memory_db_path: str = DEFAULT_MEMORY_DB
    api_catalog_prompt: str = ""
    enable_long_term_memory: bool = False
    config: HubloomConfig | None = None
    _mcp_tools: list[Any] = field(default_factory=list)

    async def close(self) -> None:
        if self.mcp_bindings is not None:
            try:
                await self.mcp_bindings.client.close()
            except Exception as exc:
                cortex_log("runtime mcp close failed", error=str(exc))
            self.mcp_bindings = None

    def create_agent(self, session_key: str) -> CortexAgent:
        """为单次对话创建 Agent（MCP 工具共享，记忆 namespace 按会话隔离）。

        LLM 解析顺序：request context（session 已绑）→ ``HubloomConfig`` → env（``create_llm``）。
        """
        key = (session_key or "").strip() or "tester_id"
        tools = ToolRegistry.from_tools(list(self._mcp_tools))
        cfg = self.config
        llm_kwargs: dict[str, str] = {}
        if api_key := _first_str(
            get_openai_api_key(),
            None if cfg is None else cfg.openai_api_key,
        ):
            llm_kwargs["api_key"] = api_key
        if model := _first_str(
            get_openai_model(),
            None if cfg is None else cfg.openai_model,
        ):
            llm_kwargs["model"] = model
        if base_url := _first_str(
            get_openai_base_url(),
            None if cfg is None else cfg.openai_base_url,
        ):
            llm_kwargs["base_url"] = base_url
        llm = create_llm(**llm_kwargs)
        long_term = self.enable_long_term_memory
        agent = CortexAgent(
            llm,
            tools=tools,
            assessor=Assessor(create_llm(**llm_kwargs)),
            session_id=key,
            enable_long_term_memory=long_term,
            include_graph_memory=long_term,
            api_catalog_prompt=self.api_catalog_prompt,
            memory_db_path=self.memory_db_path,
        )
        agent.attach_readonly_tools(knowledge_base=self.knowledge_base)
        return agent


async def build_runtime_async(
    *,
    enable_mcp: bool = True,
    memory_db_path: str | None = None,
    enable_long_term_memory: bool | None = None,
    config: HubloomConfig | None = None,
) -> CortexRuntime:
    """加载 MCP / RAG，构造可复用的 CortexRuntime。"""
    long_term = (
        ENABLE_LONG_TERM_MEMORY
        if enable_long_term_memory is None
        else enable_long_term_memory
    )
    runtime = CortexRuntime(
        enable_mcp=enable_mcp,
        memory_db_path=(memory_db_path or DEFAULT_MEMORY_DB).strip()
        or DEFAULT_MEMORY_DB,
        enable_long_term_memory=long_term,
        config=config,
    )

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
            from mcp_adapter.discovery import mcp_gateway_stdio_cmd

            command, args = mcp_gateway_stdio_cmd()
            bindings = await load_mcp_tools(
                command=command,
                args=args,
                cwd=str(SRC_ROOT),
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
        long_term_memory=runtime.enable_long_term_memory,
        memory_db=runtime.memory_db_path,
        kb_dir=os.getenv("CORTEX_KB_DIR", DEFAULT_KB_DIR),
    )
    return runtime
