"""Hubloom 运行时：读配置装配一次，按 session 跑 run_stream。

后端 / 测试只关心：

    agent = await HubloomRuntime.from_config(cfg)
    async for item in agent.run_stream(trigger, session_id=...):
        ...
    await agent.aclose()
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from agent.agent_log import configure_agent_logging
from agent.assemble import (
    build_respond_a2ui_system,
    build_respond_markdown_system,
    build_think_systems,
)
from agent.events import AgentEvent
from agent.loop.respond import PresentMode
from agent.run import RunResult, run_stream
from config import HubloomConfig
from context import set_request_context
from core.factory import create_llm
from core.models import Message
from core.provider import LLMProvider
from mcp_adapter.discovery import AgentMcpSetup, load_agent_mcp_bindings
from memory import create_memory_manager
from memory.manager import MemoryManager
from tools.builtin.memory_tool import SearchMemoryTool
from tools.registry import ToolRegistry
from tools.runner import ToolRunner


def _project_root(cfg: HubloomConfig) -> Path:
    """配置文件所在仓库根：config/env.yaml → parents[1]。"""
    if cfg.source_path:
        return Path(cfg.source_path).resolve().parents[1]
    return Path.cwd()


def _resolve_path(cfg: HubloomConfig, raw: str | None, default: str) -> Path:
    text = (raw or default).strip() or default
    path = Path(text)
    if not path.is_absolute():
        path = _project_root(cfg) / path
    return path


def _skills_dir(cfg: HubloomConfig) -> Path:
    return _resolve_path(cfg, cfg.skills_dir, "skills")


def _memory_db_path(cfg: HubloomConfig) -> str:
    path = _resolve_path(cfg, cfg.memory_db_path, "data/memory.db")
    path.parent.mkdir(parents=True, exist_ok=True)
    return str(path)


@dataclass
class HubloomRuntime:
    """进程级 Agent 运行时（LLM / MCP / system 文案）；session 在 run 时注入。"""

    cfg: HubloomConfig
    llm: LLMProvider
    think_system: str  # 工具前（含 skills / catalog）
    think_system_after: str  # 工具后（短提示）
    respond_markdown_system: str
    respond_a2ui_system: str
    default_present_mode: PresentMode
    mcp_setup: AgentMcpSetup | None
    _mcp_tools: list[Any]
    max_think_rounds: int = 5

    @classmethod
    async def from_config(
        cls,
        cfg: HubloomConfig,
        *,
        default_present_mode: PresentMode = "a2ui",
        max_think_rounds: int = 5,
    ) -> HubloomRuntime:
        if not (cfg.openai_api_key or "").strip():
            raise ValueError("HubloomConfig 未配置 llm.api_key")

        configure_agent_logging(
            agent_log=cfg.agent_log,
            cortex_log=cfg.cortex_log,
            a2a_log=cfg.a2a_log,
            memory_log=cfg.memory_log,
        )

        llm = create_llm(
            api_key=cfg.openai_api_key,
            model=cfg.openai_model,
            base_url=cfg.openai_base_url,
        )

        mcp_setup: AgentMcpSetup | None = None
        mcp_tools: list[Any] = []

        if cfg.enable_mcp:
            swagger = (cfg.mcp_swagger_url or "").strip()
            if not swagger:
                raise ValueError("mcp.enable=true 但未配置 mcp.swagger_url")

            set_request_context(
                mcp_auth_scheme=cfg.mcp_auth_scheme,
                mcp_swagger_url=swagger,
                mcp_base_url=cfg.mcp_base_url,
            )

            child_env: dict[str, str] = {}
            if cfg.mcp_auth_scheme:
                child_env["MCP_AUTH_SCHEME"] = str(cfg.mcp_auth_scheme).strip()
            if cfg.mcp_token:
                child_env["MCP_TOKEN"] = str(cfg.mcp_token).strip()

            src_cwd = str(_project_root(cfg) / "src")
            mcp_setup = await load_agent_mcp_bindings(
                swagger_url=swagger,
                base_url=cfg.mcp_base_url,
                env=child_env or None,
                cwd=src_cwd,
            )
            mcp_tools = list(mcp_setup.bindings.tools)

        think_system, think_system_after = build_think_systems(
            skills_dir=_skills_dir(cfg),
            skills_exclude=cfg.skills_exclude,
            catalog=None if mcp_setup is None else mcp_setup.catalog,
        )

        return cls(
            cfg=cfg,
            llm=llm,
            think_system=think_system,
            think_system_after=think_system_after,
            respond_markdown_system=build_respond_markdown_system(),
            respond_a2ui_system=build_respond_a2ui_system(),
            default_present_mode=default_present_mode,
            mcp_setup=mcp_setup,
            _mcp_tools=mcp_tools,
            max_think_rounds=max_think_rounds,
        )

    @classmethod
    async def from_config_file(
        cls,
        path: str | Path,
        *,
        default_present_mode: PresentMode = "a2ui",
        max_think_rounds: int = 5,
    ) -> HubloomRuntime:
        cfg = HubloomConfig.from_file(path)
        return await cls.from_config(
            cfg,
            default_present_mode=default_present_mode,
            max_think_rounds=max_think_rounds,
        )

    @property
    def memory_db_path(self) -> str:
        return _memory_db_path(self.cfg)

    def _make_memory(self, session_id: str) -> MemoryManager:
        return create_memory_manager(
            namespace=session_id,
            db_path=self.memory_db_path,
            vector_backend="none",
            graph_backend="none",
        )

    def _make_runner(self, memory: MemoryManager) -> tuple[ToolRunner, list[dict]]:
        tools: list[Any] = [SearchMemoryTool(memory), *self._mcp_tools]
        registry = ToolRegistry.from_tools(tools)
        return ToolRunner(registry), registry.list_definitions()

    async def run_stream(
        self,
        trigger: Message,
        *,
        session_id: str,
        present_mode: PresentMode | None = None,
        bearer_token: str | None = None,
        trigger_source: str = "user",
        max_think_rounds: int | None = None,
    ) -> AsyncIterator[AgentEvent | RunResult]:
        """按 session 装配 memory/tools，委托 ``agent.run.run_stream``。

        ``bearer_token``：当前用户鉴权，写入 request context，供 MCP
        ``call_tool`` 经 ``get_bearer_token()`` 透传；为空则回退 MCP_TOKEN。

        ``present_mode=auto``：Think 交班后跑 Present，再决定 Markdown / A2UI Respond。
        """
        mode: PresentMode = present_mode or self.default_present_mode
        sid = (session_id or "").strip()
        if not sid:
            raise ValueError("session_id 不能为空")

        token = (bearer_token or "").strip() or None

        set_request_context(
            bearer_token=token,
            session_id=sid,
            mcp_auth_scheme=self.cfg.mcp_auth_scheme,
            mcp_swagger_url=self.cfg.mcp_swagger_url,
            mcp_base_url=self.cfg.mcp_base_url,
        )

        memory = self._make_memory(sid)
        runner, tool_defs = self._make_runner(memory)

        async for item in run_stream(
            llm=self.llm,
            memory=memory,
            runner=runner,
            tools=tool_defs,
            trigger=trigger,
            think_system=self.think_system,
            think_system_after=self.think_system_after,
            respond_markdown_system=self.respond_markdown_system,
            respond_a2ui_system=self.respond_a2ui_system,
            present_mode=mode,
            max_think_rounds=max_think_rounds or self.max_think_rounds,
            trigger_source=trigger_source,
        ):
            yield item

    async def aclose(self) -> None:
        if self.mcp_setup is not None:
            try:
                await self.mcp_setup.bindings.client.close()
            finally:
                self.mcp_setup = None
