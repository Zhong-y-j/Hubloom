"""组装 Hubloom 运行时（门面 create / A2A 共用）。

配置经 ``HubloomConfig`` 下传；不向当前进程全局 ``os.environ`` 灌入 YAML。
MCP 子进程仅注入必要的局部 env 键。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from agents.agent_log import cortex_log
from agents.adp.assessor import Assessor
from agents.adp.cortex_agent import CortexAgent, load_knowledge_base
from hubloom.context import (
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
from retrieval.rag_bootstrap import is_rag_enabled
from tools.registry import ToolRegistry


def _first_str(*values: str | None) -> str | None:
    for value in values:
        text = (value or "").strip()
        if text:
            return text
    return None


def _llm_kwargs(config: HubloomConfig | None) -> dict[str, str]:
    """组齐 create_llm 参数：request context > HubloomConfig；不读 OPENAI_* env。"""
    api_key = _first_str(
        get_openai_api_key(),
        None if config is None else config.openai_api_key,
    )
    if not api_key:
        raise ValueError(
            "HubloomConfig.openai_api_key 未配置 "
            "(config/env.yaml 的 llm.api_key，或请求 context)"
        )
    kwargs: dict[str, str] = {"api_key": api_key}
    if model := _first_str(
        get_openai_model(),
        None if config is None else config.openai_model,
    ):
        kwargs["model"] = model
    if base_url := _first_str(
        get_openai_base_url(),
        None if config is None else config.openai_base_url,
    ):
        kwargs["base_url"] = base_url
    return kwargs


def _mcp_swagger_url(config: HubloomConfig | None) -> str:
    url = _first_str(None if config is None else config.mcp_swagger_url)
    if not url:
        raise ValueError(
            "HubloomConfig.mcp_swagger_url 未配置 "
            "(config/env.yaml 的 mcp.swagger_url；enable_mcp 时必需)"
        )
    return url


def _mcp_child_env(config: HubloomConfig) -> dict[str, str]:
    """仅给 MCP stdio 子进程的局部 env（不写当前进程 os.environ）。"""
    child_env: dict[str, str] = {}
    for key, value in (
        ("MCP_SWAGGER_URL", config.mcp_swagger_url),
        ("MCP_BASE_URL", config.mcp_base_url),
        ("MCP_AUTH_SCHEME", config.mcp_auth_scheme),
        ("MCP_TOKEN", config.mcp_token),
        ("CORTEX_AGENT_LOG", "1" if config.agent_log else None),
    ):
        if value is None:
            continue
        text = str(value).strip()
        if not text:
            continue
        if value is True:
            child_env[key] = "1"
        elif value is False:
            child_env[key] = "0"
        else:
            child_env[key] = text
    return child_env


def _memory_backend_kwargs(config: HubloomConfig | None) -> dict[str, Any]:
    """长期记忆后端参数：来自 HubloomConfig，不读 QDRANT_* / NEO4J_* / OPENAI_* env。"""
    if config is None:
        return {}
    return {
        "qdrant_url": config.qdrant_url,
        "qdrant_api_key": config.qdrant_api_key,
        "qdrant_collection": config.qdrant_collection,
        "neo4j_uri": config.neo4j_uri,
        "neo4j_user": config.neo4j_user,
        "neo4j_password": config.neo4j_password,
        "neo4j_database": config.neo4j_database,
        "neo4j_skip_dns_check": config.neo4j_skip_dns_check,
        "embedder_api_key": config.openai_api_key,
        "embedder_base_url": config.openai_base_url,
    }


def _resolve_from_config(
    config: HubloomConfig | None,
    *,
    enable_mcp: bool,
    memory_db_path: str | None,
    enable_long_term_memory: bool | None,
) -> tuple[bool, str, bool, bool, str, str]:
    """返回 enable_mcp, memory_db, long_term, rag_enabled, rag_docs, kb_dir。"""
    if config is None:
        mem = (memory_db_path or DEFAULT_MEMORY_DB).strip() or DEFAULT_MEMORY_DB
        long_term = (
            ENABLE_LONG_TERM_MEMORY
            if enable_long_term_memory is None
            else enable_long_term_memory
        )
        return enable_mcp, mem, long_term, ENABLE_RAG, "", DEFAULT_KB_DIR

    mem = (
        (memory_db_path or config.memory_db_path or DEFAULT_MEMORY_DB).strip()
        or DEFAULT_MEMORY_DB
    )
    long_term = (
        bool(config.enable_long_term_memory)
        if enable_long_term_memory is None
        and config.enable_long_term_memory is not None
        else (
            ENABLE_LONG_TERM_MEMORY
            if enable_long_term_memory is None
            else enable_long_term_memory
        )
    )
    mcp_on = config.enable_mcp if enable_mcp is True else enable_mcp
    # enable_mcp kwarg defaults True; prefer config.enable_mcp
    mcp_on = config.enable_mcp

    rag_docs = (config.rag_docs or "").strip()
    rag_on = is_rag_enabled(rag_docs, enabled=config.enable_rag)
    kb_dir = (config.kb_dir or "").strip() or DEFAULT_KB_DIR
    return mcp_on, mem, long_term, rag_on, rag_docs, kb_dir


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

        LLM：request context → ``HubloomConfig``（不读 OPENAI_* env）。
        """
        key = (session_key or "").strip() or "tester_id"
        tools = ToolRegistry.from_tools(list(self._mcp_tools))
        llm_kwargs = _llm_kwargs(self.config)
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
            **_memory_backend_kwargs(self.config),
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
    mcp_on, mem, long_term, rag_on, rag_docs, kb_dir = _resolve_from_config(
        config,
        enable_mcp=enable_mcp,
        memory_db_path=memory_db_path,
        enable_long_term_memory=enable_long_term_memory,
    )
    runtime = CortexRuntime(
        enable_mcp=mcp_on,
        memory_db_path=mem,
        enable_long_term_memory=long_term,
        config=config,
    )

    if config is not None:
        from a2a_adapter.client.registry import configure_agents
        from agents.a2a.credential.static import configure_credential
        from agents.agent_log import configure_agent_logging

        configure_agents(config.a2a_remote_agents)
        if config.a2a_static_token:
            configure_credential(token=config.a2a_static_token)
        configure_agent_logging(
            agent_log=config.agent_log,
            cortex_log=config.cortex_log,
            a2a_log=config.a2a_log,
            memory_log=config.memory_log,
        )

    if rag_on:
        runtime.knowledge_base = await load_knowledge_base(
            rag_docs=rag_docs or None,
            kb_dir=kb_dir,
            enabled=True,
            embedder_api_key=None if config is None else config.openai_api_key,
            embedder_base_url=None if config is None else config.openai_base_url,
        )

    if mcp_on:
        swagger_url = _mcp_swagger_url(config)
        base_url = None if config is None else config.mcp_base_url
        try:
            from mcp_adapter.gateway.catalog import (
                format_catalog_for_prompt,
                load_catalog,
            )

            catalog = await load_catalog(
                swagger_url=swagger_url,
                base_url=base_url,
            )
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
            child_env = _mcp_child_env(config) if config is not None else {
                "MCP_SWAGGER_URL": swagger_url,
            }
            bindings = await load_mcp_tools(
                command=command,
                args=args,
                env=child_env,
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
        rag_enabled=rag_on and runtime.knowledge_base is not None,
        long_term_memory=runtime.enable_long_term_memory,
        memory_db=runtime.memory_db_path,
        kb_dir=kb_dir,
    )
    return runtime
