"""HubloomAgent 配置（create 入参：进程级基础设施）。

用户业务 token 请在 ``HubloomAgent.session(session_id, token=...)`` 传入。
``mcp_token`` 仅作服务级兜底（等同 ``MCP_TOKEN`` env）；有 session token 时以 session 为准。
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass
class HubloomConfig:
    """单个 HubloomAgent 实例的进程级配置；显式字段优先于环境变量。

    create 时使用：Swagger、MCP base、记忆/RAG/A2A、可选服务端默认 LLM。
    用户会话：``session(session_id, token=...).run_stream(message)``。
    """

    # --- LLM（服务端默认；HTTP 演示仍可按请求覆盖 request context）---
    openai_api_key: str | None = None
    openai_model: str | None = None
    openai_base_url: str | None = None

    # --- MCP / OpenAPI（进程级网关发现）---
    enable_mcp: bool = True
    mcp_swagger_url: str | None = None
    mcp_base_url: str | None = None
    mcp_auth_scheme: str | None = None
    # 服务级兜底；有用户 session.token 时以 session 为准
    mcp_token: str | None = None

    # --- 记忆与隔离（多实例时务必分开）---
    memory_db_path: str | None = None
    enable_long_term_memory: bool | None = None

    # --- RAG（可选）---
    enable_rag: bool | None = None
    kb_dir: str | None = None
    rag_docs: str | None = None

    # --- A2A（可选）---
    public_url: str | None = None
    a2a_remote_agents: str | None = None  # JSON 字符串，与现 env 同形

    # --- 预留：手动 skill 白名单 ---
    skills: list[dict[str, Any]] | None = None

    @classmethod
    def from_env(cls) -> HubloomConfig:
        """从当前进程环境变量构造一份配置（兼容现有 .env）。"""

        def _flag(name: str) -> bool | None:
            raw = os.getenv(name)
            if raw is None or not str(raw).strip():
                return None
            return str(raw).strip().lower() in ("1", "true", "yes", "on")

        return cls(
            openai_api_key=(os.getenv("OPENAI_API_KEY") or "").strip() or None,
            openai_model=(os.getenv("OPENAI_MODEL") or "").strip() or None,
            openai_base_url=(os.getenv("OPENAI_BASE_URL") or "").strip() or None,
            enable_mcp=True,
            mcp_swagger_url=(os.getenv("MCP_SWAGGER_URL") or "").strip() or None,
            mcp_base_url=(os.getenv("MCP_BASE_URL") or "").strip() or None,
            mcp_auth_scheme=(os.getenv("MCP_AUTH_SCHEME") or "").strip() or None,
            mcp_token=(os.getenv("MCP_TOKEN") or "").strip() or None,
            memory_db_path=(os.getenv("CORTEX_MEMORY_DB") or "").strip() or None,
            enable_long_term_memory=_flag("CORTEX_ENABLE_LONG_TERM_MEMORY"),
            enable_rag=_flag("CORTEX_ENABLE_RAG"),
            kb_dir=(os.getenv("CORTEX_KB_DIR") or "").strip() or None,
            rag_docs=(os.getenv("CORTEX_RAG_DOCS") or "").strip() or None,
            public_url=(os.getenv("CORTEX_PUBLIC_URL") or "").strip() or None,
            a2a_remote_agents=(os.getenv("A2A_REMOTE_AGENTS") or "").strip() or None,
            skills=None,
        )

    @classmethod
    def from_file(cls, path: str | Path) -> HubloomConfig:
        """从 YAML/JSON 加载（尚未实现，占位）。"""
        raise NotImplementedError(
            "HubloomConfig.from_file 将在 config 重构步骤实现；请先用 HubloomConfig(...) 或 from_env()"
        )
