from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


def _clean(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text or text == "...":
        return None
    return text


def _as_bool(value: Any) -> bool | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return value
    text = str(value).strip().lower()
    if not text:
        return None
    if text in ("1", "true", "yes", "on"):
        return True
    if text in ("0", "false", "no", "off"):
        return False
    return None


def _section(data: dict[str, Any], name: str) -> dict[str, Any]:
    raw = data.get(name)
    return raw if isinstance(raw, dict) else {}


def _remote_agents_to_str(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, str):
        return _clean(value)
    if isinstance(value, (list, dict)):
        return json.dumps(value, ensure_ascii=False)
    return _clean(value)


def _as_int(value: Any) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _as_str_list(value: Any) -> list[str]:
    """解析 YAML 字符串列表；也接受逗号分隔的单个字符串。"""
    if value is None:
        return []
    if isinstance(value, str):
        text = value.strip()
        if not text or text == "...":
            return []
        return [part.strip() for part in text.split(",") if part.strip()]
    if isinstance(value, list):
        out: list[str] = []
        for item in value:
            cleaned = _clean(item)
            if cleaned:
                out.append(cleaned)
        return out
    return []


@dataclass
class HubloomConfig:
    """单个 HubloomAgent 实例的配置（对应 config/*.yaml）。"""

    # llm
    openai_api_key: str | None = None
    openai_model: str | None = None
    openai_base_url: str | None = None
    openai_timeout: int | None = None

    # mcp
    enable_mcp: bool = True
    mcp_swagger_url: str | None = None
    mcp_base_url: str | None = None
    mcp_auth_scheme: str | None = None
    mcp_token: str | None = None

    # memory / session
    memory_db_path: str | None = None
    enable_long_term_memory: bool | None = None
    consolidate_min_turns: int | None = None
    default_session_id: str | None = None

    # rag
    enable_rag: bool | None = None
    kb_dir: str | None = None
    rag_docs: str | None = None

    # a2a
    public_url: str | None = None
    a2a_remote_agents: str | None = None
    a2a_static_token: str | None = None

    # http demo
    api_host: str | None = None
    api_port: int | None = None
    api_reload: bool | None = None

    # logging
    agent_log: bool | None = None
    cortex_log: bool | None = None
    a2a_log: bool | None = None
    memory_log: bool | None = None

    # search / long-term backends
    serpapi_api_key: str | None = None
    qdrant_url: str | None = None
    qdrant_api_key: str | None = None
    qdrant_collection: str | None = None
    no_proxy: str | None = None
    neo4j_uri: str | None = None
    neo4j_user: str | None = None
    neo4j_password: str | None = None
    neo4j_database: str | None = None
    neo4j_skip_dns_check: bool | None = None

    # skills：默认注入 skills_dir 下全部 SKILL.md；skills_exclude 为目录名黑名单
    skills_dir: str | None = "skills"
    skills_exclude: list[str] = field(default_factory=list)
    source_path: str | None = field(default=None, repr=False)

    @classmethod
    def from_file(cls, path: str | Path) -> HubloomConfig:
        """从 YAML/JSON 文件加载配置对象。"""
        cfg_path = Path(path)
        if not cfg_path.is_file():
            raise FileNotFoundError(f"配置文件不存在: {cfg_path.resolve()}")

        text = cfg_path.read_text(encoding="utf-8")
        suffix = cfg_path.suffix.lower()
        if suffix in (".yaml", ".yml"):
            import yaml

            data = yaml.safe_load(text) or {}
        elif suffix == ".json":
            data = json.loads(text or "{}")
        else:
            raise ValueError(f"不支持的配置后缀: {suffix}（请用 .yaml / .yml / .json）")

        if not isinstance(data, dict):
            raise ValueError(f"配置根节点必须是 mapping: {cfg_path}")

        llm = _section(data, "llm")
        session = _section(data, "session")
        memory = _section(data, "memory")
        rag = _section(data, "rag")
        http = _section(data, "http")
        logging_cfg = _section(data, "logging")
        search = _section(data, "search")
        qdrant = _section(data, "qdrant")
        neo4j = _section(data, "neo4j")
        mcp = _section(data, "mcp")
        a2a = _section(data, "a2a")

        enable_mcp = _as_bool(mcp.get("enable"))
        if enable_mcp is None:
            enable_mcp = True

        skills_dir = _clean(data.get("skills_dir")) or "skills"

        return cls(
            openai_api_key=_clean(llm.get("api_key")),
            openai_model=_clean(llm.get("model")),
            openai_base_url=_clean(llm.get("base_url")),
            openai_timeout=_as_int(llm.get("timeout")),
            enable_mcp=enable_mcp,
            mcp_swagger_url=_clean(mcp.get("swagger_url")),
            mcp_base_url=_clean(mcp.get("base_url")),
            mcp_auth_scheme=_clean(mcp.get("auth_scheme")),
            mcp_token=_clean(mcp.get("token")),
            memory_db_path=_clean(memory.get("db_path")),
            enable_long_term_memory=_as_bool(memory.get("enable_long_term")),
            consolidate_min_turns=_as_int(memory.get("consolidate_min_turns")),
            default_session_id=_clean(session.get("default_session_id")),
            enable_rag=_as_bool(rag.get("enable")),
            kb_dir=_clean(rag.get("kb_dir")),
            rag_docs=_clean(rag.get("docs")),
            public_url=_clean(a2a.get("public_url")),
            a2a_remote_agents=_remote_agents_to_str(a2a.get("remote_agents")),
            a2a_static_token=_clean(a2a.get("static_token")),
            api_host=_clean(http.get("host")),
            api_port=_as_int(http.get("port")),
            api_reload=_as_bool(http.get("reload")),
            agent_log=_as_bool(logging_cfg.get("agent_log")),
            cortex_log=_as_bool(logging_cfg.get("cortex_log")),
            a2a_log=_as_bool(logging_cfg.get("a2a_log")),
            memory_log=_as_bool(logging_cfg.get("memory_log")),
            serpapi_api_key=_clean(search.get("serpapi_api_key")),
            qdrant_url=_clean(qdrant.get("url")),
            qdrant_api_key=_clean(qdrant.get("api_key")),
            qdrant_collection=_clean(qdrant.get("collection")),
            no_proxy=_clean(qdrant.get("no_proxy")),
            neo4j_uri=_clean(neo4j.get("uri")),
            neo4j_user=_clean(neo4j.get("user")),
            neo4j_password=_clean(neo4j.get("password")),
            neo4j_database=_clean(neo4j.get("database")),
            neo4j_skip_dns_check=_as_bool(neo4j.get("skip_dns_check")),
            skills_dir=skills_dir,
            skills_exclude=_as_str_list(data.get("skills_exclude")),
            source_path=str(cfg_path.resolve()),
        )
