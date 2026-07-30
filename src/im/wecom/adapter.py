"""企微回调 → 换 Token → HubloomRuntime → 主动推送。

可选注入 ``RedisSessionQueue`` + ``SessionWorker``：文字消息入 Redis 按 session 串行；
未注入时保持原进程内 ``create_task``（示例站未改装配前仍可用）。
"""

from __future__ import annotations

import asyncio
from collections import OrderedDict
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

from loguru import logger

from im.session_queue import (
    EnqueueResult,
    RedisSessionQueue,
    SessionJob,
    SessionWorker,
)
from im.wecom.client import WeComAppClient
from im.wecom.crypto import WeComCrypto, WeComCryptoError, parse_message_xml
from im.wecom.token_resolve import (
    BusinessTokenResolver,
    TokenResolveError,
)

RunAgentFn = Callable[..., Awaitable[str]]
# run_agent(message, *, session_id, bearer_token) -> reply markdown


@dataclass
class WeComAdapterConfig:
    session_prefix: str = "wecom"
    # 企微宜短：默认 650；客户端 markdown 硬上限 2048
    max_reply_chars: int = 650


class MsgIdDeduper:
    """进程内 MsgId 排重（无 Redis 队列时作补充；队列侧另有 Redis dedupe）。"""

    def __init__(self, max_size: int = 2000) -> None:
        self._max = max_size
        self._seen: OrderedDict[str, None] = OrderedDict()
        self._lock = asyncio.Lock()

    async def seen_or_add(self, msg_id: str) -> bool:
        """若已见过返回 True；否则登记并返回 False。"""
        key = (msg_id or "").strip()
        if not key:
            return False
        async with self._lock:
            if key in self._seen:
                return True
            self._seen[key] = None
            while len(self._seen) > self._max:
                self._seen.popitem(last=False)
            return False


def wecom_message_to_job(
    msg: dict[str, Any],
    *,
    session_id: str,
    text: str | None = None,
) -> SessionJob:
    """把企微明文消息 dict 转成 ``SessionJob``（供外部入队）。"""
    userid = (msg.get("FromUserName") or "").strip()
    msg_id = (msg.get("MsgId") or "").strip()
    content = (text if text is not None else (msg.get("Content") or "")).strip()
    return SessionJob(
        session_id=session_id,
        source="wecom",
        text=content,
        dedupe_key=msg_id or None,
        meta={
            "wecom_userid": userid,
            "msg_type": (msg.get("MsgType") or "").strip(),
            "msg_id": msg_id,
        },
    )


class WeComChatAdapter:
    """处理 URL 验证与消息回调（异步跑 Agent）。

    装配 Redis 队列时传入 ``session_queue``；``session_worker`` 可省略（自动创建）。
    """

    def __init__(
        self,
        *,
        crypto: WeComCrypto,
        client: WeComAppClient,
        token_resolver: BusinessTokenResolver,
        run_agent: RunAgentFn,
        config: WeComAdapterConfig | None = None,
        deduper: MsgIdDeduper | None = None,
        session_queue: RedisSessionQueue | None = None,
        session_worker: SessionWorker | None = None,
    ) -> None:
        self.crypto = crypto
        self.client = client
        self.token_resolver = token_resolver
        self.run_agent = run_agent
        self.config = config or WeComAdapterConfig()
        self.deduper = deduper or MsgIdDeduper()
        self.session_queue = session_queue
        if session_queue is not None:
            self.session_worker = session_worker or SessionWorker(
                session_queue, self._handle_jobs
            )
        else:
            self.session_worker = session_worker

    @property
    def uses_redis_queue(self) -> bool:
        return self.session_queue is not None and self.session_worker is not None

    def session_id_for(self, userid: str) -> str:
        prefix = (self.config.session_prefix or "wecom").strip() or "wecom"
        return f"{prefix}:{userid.strip()}"

    def verify_url(
        self,
        *,
        msg_signature: str,
        timestamp: str,
        nonce: str,
        echostr: str,
    ) -> str:
        return self.crypto.verify_url(msg_signature, timestamp, nonce, echostr)

    def handle_callback_sync_ack(
        self,
        *,
        msg_signature: str,
        timestamp: str,
        nonce: str,
        post_data: str | bytes,
    ) -> tuple[str, dict[str, Any] | None]:
        """验签解密；返回 (明文 xml 或空, 解析后的消息 dict)。

        调用方应立即对企微返回空 200，再 ``schedule_handle_message``。
        """
        plain = self.crypto.decrypt_message(
            msg_signature, timestamp, nonce, post_data
        )
        msg = parse_message_xml(plain)
        return plain, msg

    def schedule_handle_message(self, msg: dict[str, Any]) -> None:
        if self.uses_redis_queue:
            asyncio.create_task(self._safe_enqueue(msg))
        else:
            asyncio.create_task(self._safe_handle(msg))

    async def enqueue_message(self, msg: dict[str, Any]) -> EnqueueResult | None:
        """显式入队（需已装配 Redis 队列）。非文本会直接推送提示并返回 None。"""
        if not self.uses_redis_queue:
            raise RuntimeError("未装配 session_queue，无法 enqueue_message")
        return await self._enqueue_from_msg(msg)

    async def _safe_enqueue(self, msg: dict[str, Any]) -> None:
        try:
            await self._enqueue_from_msg(msg)
        except Exception:
            logger.exception("wecom enqueue failed")

    async def _enqueue_from_msg(self, msg: dict[str, Any]) -> EnqueueResult | None:
        assert self.session_worker is not None
        msg_type = (msg.get("MsgType") or "").strip().lower()
        userid = (msg.get("FromUserName") or "").strip()
        if not userid:
            logger.warning("wecom message missing FromUserName")
            return None

        if msg_type != "text":
            await self._push(userid, "暂只支持文字消息，请直接发送文本问题。")
            return None

        content = (msg.get("Content") or "").strip()
        if not content:
            await self._push(userid, "请发送非空文字消息。")
            return None

        session_id = self.session_id_for(userid)
        job = wecom_message_to_job(msg, session_id=session_id, text=content)
        result = await self.session_worker.enqueue_and_kick(job)
        if result.duplicate:
            logger.info(
                "wecom duplicate skipped via redis | dedupe={} | job_id={}",
                job.dedupe_key,
                job.job_id,
            )
        return result

    async def _handle_jobs(self, jobs: list[SessionJob]) -> None:
        """Worker 回调：现在 jobs 长度为 1；后期合并时可能多条。"""
        if not jobs:
            return
        # 预留：合并期在此拼接 texts / merged_from，再跑一轮
        job = jobs[0]
        userid = str(job.meta.get("wecom_userid") or "").strip()
        if not userid:
            logger.warning("wecom job missing wecom_userid | job_id={}", job.job_id)
            return

        try:
            bearer = job.bearer_token or await self.token_resolver.resolve(userid)
        except TokenResolveError as exc:
            await self._push(userid, str(exc))
            return

        try:
            reply = await self.run_agent(
                job.text,
                session_id=job.session_id,
                bearer_token=bearer,
            )
        except Exception as exc:
            logger.exception("wecom agent run failed | user={}", userid)
            await self._push(userid, f"处理失败：{str(exc)[:200]}")
            return

        await self._push(userid, self._format_reply(reply, job.session_id))

    async def _safe_handle(self, msg: dict[str, Any]) -> None:
        try:
            await self.handle_message(msg)
        except Exception:
            logger.exception("wecom handle_message failed")

    async def handle_message(self, msg: dict[str, Any]) -> None:
        """进程内直接处理（无 Redis 队列时的路径）。"""
        msg_type = (msg.get("MsgType") or "").strip().lower()
        userid = (msg.get("FromUserName") or "").strip()
        msg_id = (msg.get("MsgId") or "").strip()
        if not userid:
            logger.warning("wecom message missing FromUserName")
            return

        if await self.deduper.seen_or_add(msg_id):
            logger.info("wecom duplicate MsgId skipped | msgid={}", msg_id)
            return

        if msg_type != "text":
            await self._push(
                userid,
                "暂只支持文字消息，请直接发送文本问题。",
            )
            return

        content = (msg.get("Content") or "").strip()
        if not content:
            await self._push(userid, "请发送非空文字消息。")
            return

        try:
            bearer = await self.token_resolver.resolve(userid)
        except TokenResolveError as exc:
            await self._push(userid, str(exc))
            return

        session_id = self.session_id_for(userid)
        try:
            reply = await self.run_agent(
                content,
                session_id=session_id,
                bearer_token=bearer,
            )
        except Exception as exc:
            logger.exception("wecom agent run failed | user={}", userid)
            await self._push(userid, f"处理失败：{str(exc)[:200]}")
            return

        await self._push(userid, self._format_reply(reply, session_id))

    def _format_reply(self, reply: str, session_id: str) -> str:
        text = (reply or "").strip() or "（无回复内容）"
        max_chars = self.config.max_reply_chars
        footer = f"\n\n——\n详情见网页会话 `{session_id}`"
        if len(text) > max_chars:
            keep = max(40, max_chars - len(footer) - 12)
            return text[:keep] + "\n…(已截断)" + footer
        if len(text) + len(footer) <= max_chars:
            return text + footer
        return text

    async def _push(self, userid: str, content: str) -> None:
        try:
            await self.client.send_markdown(userid=userid, content=content)
        except Exception:
            logger.warning("wecom markdown send failed, fallback text")
            await self.client.send_text(userid=userid, content=content)


async def run_agent_via_runtime(
    message: str,
    *,
    session_id: str,
    bearer_token: str | None,
    runtime: Any,
    wait_profile: str | None = "turn_based",
) -> str:
    """兼容旧调用：按 session 锁跑一轮 Typed ReAct，返回短推送正文。

    新代码请用 ``server.assembly.run_wecom_agent_turn``。
    """
    from server.assembly import run_wecom_agent_turn

    return await run_wecom_agent_turn(
        runtime,
        message,
        session_id=session_id,
        bearer_token=bearer_token,
        wait_profile=wait_profile,
    )
