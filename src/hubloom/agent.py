"""HubloomAgent 对外门面。

推荐用法::

    from hubloom import HubloomAgent, HubloomConfig

    cfg = HubloomConfig(
        mcp_swagger_url="...",
        openai_api_key="...",
        memory_db_path="data/memory.db",
    )
    app = await HubloomAgent.create(cfg)
    try:
        sess = app.session("user-1", token="...")
        async for event in sess.run_stream("帮我查订单"):
            ...
    finally:
        await app.close()

- ``create(config)``：进程级装配（Swagger / LLM 默认 / 记忆等），不要用户 token
- ``session(session_id, token=...)``：打开当前用户会话
- ``HubloomSession.run_stream(message)``：往该会话发内容
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import TYPE_CHECKING

from hubloom.context import (
    get_mcp_auth_scheme,
    get_mcp_base_url,
    get_mcp_swagger_url,
    get_openai_api_key,
    get_openai_base_url,
    get_openai_model,
    set_request_context,
)
from hubloom.config import HubloomConfig
from hubloom.runtime import CortexRuntime, build_runtime_async
from hubloom.session import format_session_id

if TYPE_CHECKING:
    from agents.adp.cortex_agent import CortexAgent
    from agents.events import AgentEvent


def _clean(value: str | None) -> str | None:
    text = (value or "").strip()
    return text or None


class HubloomSession:
    """一次用户会话：持有 session_id + 用户 token，通过 ``run_stream`` 发消息。

    内部按需构造编排用的 ``CortexAgent``；调用方不必关心。
    """

    def __init__(
        self,
        app: HubloomAgent,
        session_id: str,
        *,
        token: str | None = None,
    ) -> None:
        self._app = app
        self._session_id = (session_id or "").strip() or "default"
        self._token = _clean(token)
        self._last_agent: CortexAgent | None = None

    @property
    def session_id(self) -> str:
        return self._session_id

    def _bind_and_create_agent(self) -> CortexAgent:
        """绑定本会话凭证，并用 create 时的 Config 补齐 LLM 等默认值。

        若调用方（如 HTTP）已预先写入 request context 中的 openai_*，则保留之。
        """
        cfg = self._app.config
        set_request_context(
            session_id=format_session_id(self._session_id),
            bearer_token=self._token or _clean(cfg.mcp_token),
            openai_api_key=_clean(get_openai_api_key()) or _clean(cfg.openai_api_key),
            openai_model=_clean(get_openai_model()) or _clean(cfg.openai_model),
            openai_base_url=_clean(get_openai_base_url())
            or _clean(cfg.openai_base_url),
            mcp_auth_scheme=_clean(get_mcp_auth_scheme())
            or _clean(cfg.mcp_auth_scheme),
            mcp_swagger_url=_clean(get_mcp_swagger_url())
            or _clean(cfg.mcp_swagger_url),
            mcp_base_url=_clean(get_mcp_base_url()) or _clean(cfg.mcp_base_url),
        )
        return self._app.runtime.create_agent(self._session_id)

    async def run_stream(self, message: str) -> AsyncIterator[AgentEvent]:
        """向当前会话发送用户消息并流式产出事件。"""
        agent = self._bind_and_create_agent()
        self._last_agent = agent
        async for event in agent.run_stream(message):
            yield event

    def get_last_outcome(self):
        """上一轮 ``run_stream`` 的编排结果（若有）。"""
        if self._last_agent is None:
            return None
        return self._last_agent.get_last_outcome()

    def __repr__(self) -> str:
        return f"HubloomSession(session_id={self._session_id!r})"


class HubloomAgent:
    """可多实例的 Hubloom 运行时门面。

    - ``create``：装配进程级资源（无用户 token）
    - ``session``：打开会话（session_id + token）
    - 发消息：``session(...).run_stream(message)``
    """

    def __init__(
        self,
        config: HubloomConfig,
        runtime: CortexRuntime,
    ) -> None:
        self._config = config
        self._runtime = runtime

    @property
    def config(self) -> HubloomConfig:
        return self._config

    @property
    def runtime(self) -> CortexRuntime:
        return self._runtime

    @classmethod
    async def create(cls, config: HubloomConfig | None = None) -> HubloomAgent:
        """异步构造：配置缺省时使用 ``HubloomConfig.from_env()``。

        不要求用户 token；网关发现与 catalog 在此完成。
        """
        cfg = config if config is not None else HubloomConfig.from_env()
        cls._apply_config_to_environ(cfg)

        runtime = await build_runtime_async(
            enable_mcp=cfg.enable_mcp,
            memory_db_path=cfg.memory_db_path,
            enable_long_term_memory=cfg.enable_long_term_memory,
            config=cfg,
        )
        return cls(config=cfg, runtime=runtime)

    def replace_runtime(self, runtime: CortexRuntime) -> None:
        """HTTP ``/v1/config/apply`` 等场景下热替换共享 runtime。"""
        runtime.config = self._config
        self._runtime = runtime

    def session(
        self,
        session_id: str = "default",
        *,
        token: str | None = None,
    ) -> HubloomSession:
        """打开当前用户会话。

        只接收 ``session_id`` 与用户 ``token``；Swagger / LLM 等来自 ``create`` 时的 Config。
        发送内容请用返回值的 ``run_stream``。
        """
        return HubloomSession(self, session_id, token=token)

    async def close(self) -> None:
        """释放本实例持有的 MCP 等资源。"""
        await self._runtime.close()

    @staticmethod
    def _apply_config_to_environ(cfg: HubloomConfig) -> None:
        """将进程级 config 写回 os.environ，供 catalog / 现有加载逻辑读取。

        同进程多实例仍可能互抢全局 env；后续改为显式注入后可移除。
        """
        import os

        def _set(key: str, value: str | None) -> None:
            if value is not None and str(value).strip():
                os.environ[key] = str(value).strip()

        _set("OPENAI_API_KEY", cfg.openai_api_key)
        _set("OPENAI_MODEL", cfg.openai_model)
        _set("OPENAI_BASE_URL", cfg.openai_base_url)
        _set("MCP_SWAGGER_URL", cfg.mcp_swagger_url)
        _set("MCP_BASE_URL", cfg.mcp_base_url)
        _set("MCP_AUTH_SCHEME", cfg.mcp_auth_scheme)
        _set("MCP_TOKEN", cfg.mcp_token)
        _set("CORTEX_MEMORY_DB", cfg.memory_db_path)
        _set("CORTEX_KB_DIR", cfg.kb_dir)
        _set("CORTEX_RAG_DOCS", cfg.rag_docs)
        _set("CORTEX_PUBLIC_URL", cfg.public_url)
        _set("A2A_REMOTE_AGENTS", cfg.a2a_remote_agents)
        if cfg.enable_long_term_memory is not None:
            os.environ["CORTEX_ENABLE_LONG_TERM_MEMORY"] = (
                "1" if cfg.enable_long_term_memory else "0"
            )
        if cfg.enable_rag is not None:
            os.environ["CORTEX_ENABLE_RAG"] = "1" if cfg.enable_rag else "0"

    def __repr__(self) -> str:
        mem = self._config.memory_db_path or "(default)"
        return f"HubloomAgent(memory_db_path={mem!r}, enable_mcp={self._config.enable_mcp})"


async def main() -> None:
    """本地冒烟：``uv run python -m hubloom.agent``（token 从 MCP_TOKEN / 参数传入）。"""
    import os

    from agents.events import FinalAnswerDeltaEvent, FinalAnswerEvent, TextDeltaEvent

    cfg = HubloomConfig.from_env()
    app = await HubloomAgent.create(cfg)
    try:
        session = app.session("user-1", token=os.getenv("MCP_TOKEN"))
        async for event in session.run_stream("列出所有小区"):
            if isinstance(event, (FinalAnswerDeltaEvent, TextDeltaEvent)):
                print(event.delta, end="", flush=True)
            elif isinstance(event, FinalAnswerEvent):
                print("\n---\n", event.content)
            else:
                print(type(event).__name__, event)
    finally:
        await app.close()


if __name__ == "__main__":
    import asyncio

    asyncio.run(main())
