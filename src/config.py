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
    mcp_transport: str | None = None  # stdio | http；默认 stdio
    mcp_swagger_url: str | None = None
    mcp_base_url: str | None = None
    mcp_url: str | None = None  # transport=http 时主路 URL
    mcp_auth_scheme: str | None = None
    mcp_remotes: list[dict[str, Any]] = field(default_factory=list)
    mcp_serve_host: str | None = None
    mcp_serve_port: int | None = None
    mcp_serve_path: str | None = None

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

    # hubloom serve（http.host / http.port）
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

    # agent：默认 Wait Profile（入口可在 run_stream 覆盖）
    default_wait_profile: str = "turn_based"

    # redis：SessionStore（挂起/pending）与按 session 分布式锁（必填）
    redis_url: str | None = None
    redis_session_ttl_seconds: int | None = None
    redis_lock_ttl_seconds: int | None = None

    # events：业务推送入站（POST /v1/events）
    events_enable: bool = False
    events_shared_secret: str | None = None
    events_result_callback_url: str | None = None
    events_catalog: dict[str, Any] = field(default_factory=dict)

    # im.wecom：企业微信自建应用对话入口
    wecom_enable: bool = False
    wecom_corp_id: str | None = None
    wecom_corp_secret: str | None = None
    wecom_agent_id: int | None = None
    wecom_token: str | None = None
    wecom_encoding_aes_key: str | None = None
    wecom_session_prefix: str = "wecom"
    wecom_token_resolve: dict[str, Any] = field(default_factory=dict)

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
        events = _section(data, "events")
        im = _section(data, "im")
        wecom = _section(im, "wecom")

        enable_mcp = _as_bool(mcp.get("enable"))
        if enable_mcp is None:
            enable_mcp = True

        mcp_transport = (_clean(mcp.get("transport")) or "stdio").lower()
        if mcp_transport not in ("stdio", "http"):
            raise ValueError(
                f"mcp.transport 仅支持 stdio|http，收到: {mcp_transport!r}"
            )

        remotes_raw = mcp.get("remotes")
        mcp_remotes: list[dict[str, Any]] = []
        if isinstance(remotes_raw, list):
            for i, item in enumerate(remotes_raw):
                if not isinstance(item, dict):
                    raise ValueError(f"mcp.remotes[{i}] 必须是 mapping")
                mcp_remotes.append(dict(item))

        serve = _section(mcp, "serve")

        events_enable = _as_bool(events.get("enable"))
        if events_enable is None:
            events_enable = False

        catalog_raw = events.get("catalog")
        events_catalog: dict[str, Any] = (
            dict(catalog_raw) if isinstance(catalog_raw, dict) else {}
        )

        wecom_enable = _as_bool(wecom.get("enable"))
        if wecom_enable is None:
            wecom_enable = False

        token_resolve_raw = wecom.get("token_resolve")
        wecom_token_resolve: dict[str, Any] = (
            dict(token_resolve_raw) if isinstance(token_resolve_raw, dict) else {}
        )

        agent_id = _as_int(wecom.get("agent_id"))
        session_prefix = _clean(wecom.get("session_prefix")) or "wecom"

        redis_sec = data.get("redis") or {}
        if not isinstance(redis_sec, dict):
            redis_sec = {}

        skills_dir = _clean(data.get("skills_dir")) or "skills"

        agent_sec = _section(data, "agent")
        default_wait = (
            _clean(agent_sec.get("default_wait_profile"))
            or _clean(data.get("default_wait_profile"))
            or "turn_based"
        )

        return cls(
            openai_api_key=_clean(llm.get("api_key")),
            openai_model=_clean(llm.get("model")),
            openai_base_url=_clean(llm.get("base_url")),
            openai_timeout=_as_int(llm.get("timeout")),
            enable_mcp=enable_mcp,
            mcp_transport=mcp_transport,
            mcp_swagger_url=_clean(mcp.get("swagger_url")),
            mcp_base_url=_clean(mcp.get("base_url")),
            mcp_url=_clean(mcp.get("url")),
            mcp_auth_scheme=_clean(mcp.get("auth_scheme")),
            mcp_remotes=mcp_remotes,
            mcp_serve_host=_clean(serve.get("host")),
            mcp_serve_port=_as_int(serve.get("port")),
            mcp_serve_path=_clean(serve.get("path")),
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
            default_wait_profile=default_wait,
            redis_url=_clean(redis_sec.get("url")),
            redis_session_ttl_seconds=_as_int(redis_sec.get("session_ttl_seconds")),
            redis_lock_ttl_seconds=_as_int(redis_sec.get("lock_ttl_seconds")),
            events_enable=events_enable,
            events_shared_secret=_clean(events.get("shared_secret")),
            events_result_callback_url=_clean(events.get("result_callback_url")),
            events_catalog=events_catalog,
            wecom_enable=wecom_enable,
            wecom_corp_id=_clean(wecom.get("corp_id")),
            wecom_corp_secret=_clean(wecom.get("corp_secret")),
            wecom_agent_id=agent_id,
            wecom_token=_clean(wecom.get("token")),
            wecom_encoding_aes_key=_clean(wecom.get("encoding_aes_key")),
            wecom_session_prefix=session_prefix,
            wecom_token_resolve=wecom_token_resolve,
            source_path=str(cfg_path.resolve()),
        )
