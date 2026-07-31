"""Serve 侧装配：Events Dispatcher / 企微 Adapter（不绑路由）。"""

from __future__ import annotations

import secrets
from typing import Any

from redis.asyncio import Redis

from agent.run import RunResult
from core.models import Message, Role
from events.agent_runner import StreamHostAgentRunner
from events.catalog import EventCatalog, resolve_events_skill_dir
from events.dispatcher import EventDispatcher
from events.idempotency import create_idempotency_store
from events.session_gate import create_session_gate
from im.session_queue import create_session_queue
from im.wecom.adapter import WeComAdapterConfig, WeComChatAdapter
from im.wecom.client import WeComAppClient
from im.wecom.crypto import WeComCrypto
from im.wecom.token_resolve import BusinessTokenResolver, TokenResolveConfig
from runtime import HubloomRuntime

# 企微默认短回复上限（可被 im.wecom.max_reply_chars 覆盖）
DEFAULT_WECOM_MAX_REPLY_CHARS = 650

# 企微通道：注入 system（不拼进用户消息，避免污染会话历史）
_WECOM_SYSTEM_EXTRA = (
    "## 当前通道：企业微信\n"
    "请用纯文本简短回复（不要 Markdown / 代码块 / 表格）："
    "先给结论，缺参时用编号列出即可；"
    "少用长列表与大段说明。"
)


def build_event_dispatcher(
    runtime: HubloomRuntime,
    *,
    redis: Redis | None = None,
) -> EventDispatcher | None:
    """``events.enable=true`` 时装配 Dispatcher；否则返回 None。"""
    cfg = runtime.cfg
    if not cfg.events_enable:
        return None

    redis_url = (cfg.redis_url or "").strip()
    if not redis_url and redis is None:
        raise ValueError("events.enable=true 时需要 redis.url")

    client = redis
    if client is None:
        client = getattr(runtime, "_redis_async", None)
    if client is None:
        client = Redis.from_url(redis_url, decode_responses=True)

    events_dir = resolve_events_skill_dir(
        skills_dir=cfg.skills_dir,
        source_path=cfg.source_path,
    )
    catalog = EventCatalog.load(
        events_dir=events_dir,
        config_catalog=cfg.events_catalog,
    )
    dispatcher = EventDispatcher(
        catalog=catalog,
        idempotency=create_idempotency_store(
            redis_url=redis_url or "redis://localhost:6379/0",
            redis=client,
        ),
        session_gate=create_session_gate(
            redis_url=redis_url or "redis://localhost:6379/0",
            redis=client,
        ),
        result_callback_url=cfg.events_result_callback_url,
        wait_profile="no_wait",
    )
    dispatcher.bind_agent(StreamHostAgentRunner(runtime, wait_profile="no_wait"))
    return dispatcher


def check_event_secret(cfg: Any, header_secret: str | None) -> None:
    """校验 ``X-Event-Secret``；未配置 shared_secret 则跳过。"""
    from fastapi import HTTPException

    expected = (getattr(cfg, "events_shared_secret", None) or "").strip()
    if not expected:
        return
    got = (header_secret or "").strip()
    # compare_digest 仅支持同类型且 ASCII str 或 bytes；统一按 utf-8 bytes 比较
    if not got or not secrets.compare_digest(
        got.encode("utf-8"),
        expected.encode("utf-8"),
    ):
        raise HTTPException(status_code=401, detail="无效的 X-Event-Secret")


async def run_wecom_agent_turn(
    runtime: HubloomRuntime,
    message: str,
    *,
    session_id: str,
    bearer_token: str | None,
    wait_profile: str | None = "turn_based",
) -> str:
    """企微通道跑一轮 Typed ReAct，返回推送正文。"""
    user_text = (message or "").strip()
    async with runtime.session_lock.hold(session_id):
        final: RunResult | None = None
        async for item in runtime.run_stream(
            Message(role=Role.USER, content=user_text),
            session_id=session_id,
            bearer_token=bearer_token,
            wait_profile=wait_profile,
            trigger_source="user",
            system_extra=_WECOM_SYSTEM_EXTRA,
        ):
            if isinstance(item, RunResult):
                final = item
        if final is None:
            raise RuntimeError("未收到编排结果")
        if not final.ok:
            raise RuntimeError(final.error or "运行失败")
        content = (final.content or "").strip()
        if final.pending is not None or final.status in (
            "awaiting_user",
            "waiting_user",
        ):
            tip = (
                f"\n\n（需补充信息：请在网页打开会话 `{session_id}` "
                "继续，或在企微直接回复。）"
            )
            content = (content + tip).strip()
        return content or "（无回复内容）"


def build_wecom_adapter(
    runtime: HubloomRuntime,
    *,
    redis: Redis | None = None,
) -> WeComChatAdapter | None:
    """``im.wecom.enable=true`` 时装配 Adapter + Redis 队列。"""
    cfg = runtime.cfg
    if not cfg.wecom_enable:
        return None

    corp_id = (cfg.wecom_corp_id or "").strip()
    corp_secret = (cfg.wecom_corp_secret or "").strip()
    token = (cfg.wecom_token or "").strip()
    aes_key = (cfg.wecom_encoding_aes_key or "").strip()
    agent_id = cfg.wecom_agent_id
    if not corp_id or not corp_secret or agent_id is None:
        raise ValueError("im.wecom.enable=true 时需要 corp_id / corp_secret / agent_id")
    if not token or not aes_key:
        raise ValueError(
            "im.wecom.enable=true 时需要 token / encoding_aes_key（回调验签）"
        )

    redis_url = (cfg.redis_url or "").strip()
    if not redis_url and redis is None:
        raise ValueError("im.wecom.enable=true 时需要 redis.url")

    client_redis = redis
    if client_redis is None:
        client_redis = getattr(runtime, "_redis_async", None)
    if client_redis is None:
        client_redis = Redis.from_url(redis_url, decode_responses=True)

    queue = create_session_queue(
        redis_url=redis_url or "redis://localhost:6379/0",
        redis=client_redis,
    )

    max_chars = int(
        getattr(cfg, "wecom_max_reply_chars", None) or DEFAULT_WECOM_MAX_REPLY_CHARS
    )
    max_chars = max(200, min(max_chars, 2000))

    tr_cfg = TokenResolveConfig.from_dict(cfg.wecom_token_resolve)
    if tr_cfg is not None:
        resolver: Any = BusinessTokenResolver(tr_cfg)
    else:

        class _EmptyTokenResolver:
            async def resolve(self, wecom_userid: str) -> str:
                del wecom_userid
                return ""

        resolver = _EmptyTokenResolver()

    async def _run_agent(
        message: str,
        *,
        session_id: str,
        bearer_token: str | None = None,
    ) -> str:
        return await run_wecom_agent_turn(
            runtime,
            message,
            session_id=session_id,
            bearer_token=bearer_token,
        )

    return WeComChatAdapter(
        crypto=WeComCrypto(token, aes_key, corp_id),
        client=WeComAppClient(
            corp_id=corp_id,
            corp_secret=corp_secret,
            agent_id=int(agent_id),
        ),
        token_resolver=resolver,
        run_agent=_run_agent,
        config=WeComAdapterConfig(
            session_prefix=cfg.wecom_session_prefix or "wecom",
            max_reply_chars=max_chars,
        ),
        session_queue=queue,
    )
