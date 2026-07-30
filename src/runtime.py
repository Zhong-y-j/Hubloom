"""Hubloom 运行时：读配置装配一次，按 session 跑 Typed ReAct（Step 1）。

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
from agent.assemble import build_agent_systems
from agent.events import AgentEvent
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
from tools.builtin.skill_tools import build_skill_tools, clear_read_skill_turn_state
from tools.registry import ToolRegistry
from tools.runner import ToolRunner


def _project_root(cfg: HubloomConfig) -> Path:
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
    """进程级 Agent 运行时（LLM / MCP / system）；session 在 run 时注入。"""

    cfg: HubloomConfig
    llm: LLMProvider
    system_before: str
    system_after: str
    mcp_setup: AgentMcpSetup | None
    _mcp_tools: list[Any]
    max_rounds: int = 8

    @classmethod
    async def from_config(
        cls,
        cfg: HubloomConfig,
        *,
        max_rounds: int = 8,
        # 兼容旧调用方关键字（已忽略）
        default_present_mode: str | None = None,
        max_think_rounds: int | None = None,
    ) -> HubloomRuntime:
        del default_present_mode  # Step1 已取消 A2UI / present_mode
        if max_think_rounds is not None:
            max_rounds = max_think_rounds

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

        system_before, system_after = build_agent_systems(
            skills_dir=_skills_dir(cfg),
            skills_exclude=cfg.skills_exclude,
            catalog=None if mcp_setup is None else mcp_setup.catalog,
        )

        return cls(
            cfg=cfg,
            llm=llm,
            system_before=system_before,
            system_after=system_after,
            mcp_setup=mcp_setup,
            _mcp_tools=mcp_tools,
            max_rounds=max_rounds,
        )

    @classmethod
    async def from_config_file(
        cls,
        path: str | Path,
        *,
        max_rounds: int = 8,
        default_present_mode: str | None = None,
        max_think_rounds: int | None = None,
    ) -> HubloomRuntime:
        cfg = HubloomConfig.from_file(path)
        return await cls.from_config(
            cfg,
            max_rounds=max_rounds,
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
        skill_tools = build_skill_tools(
            skills_dir=_skills_dir(self.cfg),
            skills_exclude=self.cfg.skills_exclude,
        )
        tools: list[Any] = [SearchMemoryTool(memory), *skill_tools, *self._mcp_tools]
        registry = ToolRegistry.from_tools(tools)
        return ToolRunner(registry), registry.list_definitions()

    async def run_stream(
        self,
        trigger: Message | list[Message],
        *,
        session_id: str,
        bearer_token: str | None = None,
        trigger_source: str = "user",
        max_rounds: int | None = None,
        # 兼容旧关键字
        present_mode: str | None = None,
        max_think_rounds: int | None = None,
    ) -> AsyncIterator[AgentEvent | RunResult]:
        del present_mode
        if max_think_rounds is not None:
            max_rounds = max_think_rounds

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
        clear_read_skill_turn_state()

        memory = self._make_memory(sid)
        runner, tool_defs = self._make_runner(memory)

        async for item in run_stream(
            llm=self.llm,
            memory=memory,
            runner=runner,
            tools=tool_defs,
            trigger=trigger,
            system_before=self.system_before,
            system_after=self.system_after,
            max_rounds=max_rounds or self.max_rounds,
            trigger_source=trigger_source,
        ):
            yield item

    async def aclose(self) -> None:
        if self.mcp_setup is not None:
            try:
                await self.mcp_setup.bindings.client.close()
            finally:
                self.mcp_setup = None
