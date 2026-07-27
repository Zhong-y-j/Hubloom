"""企微回调 → 换 Token → HubloomRuntime → 主动推送。"""

from __future__ import annotations

import asyncio
from collections import OrderedDict
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

from loguru import logger

from agent.run import RunResult
from context import clear_request_context
from core.models import Message, Role
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
    max_reply_chars: int = 3500


class MsgIdDeduper:
    """进程内 MsgId 排重。"""

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


class WeComChatAdapter:
    """处理 URL 验证与消息回调（异步跑 Agent）。"""

    def __init__(
        self,
        *,
        crypto: WeComCrypto,
        client: WeComAppClient,
        token_resolver: BusinessTokenResolver,
        run_agent: RunAgentFn,
        config: WeComAdapterConfig | None = None,
        deduper: MsgIdDeduper | None = None,
    ) -> None:
        self.crypto = crypto
        self.client = client
        self.token_resolver = token_resolver
        self.run_agent = run_agent
        self.config = config or WeComAdapterConfig()
        self.deduper = deduper or MsgIdDeduper()

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
        asyncio.create_task(self._safe_handle(msg))

    async def _safe_handle(self, msg: dict[str, Any]) -> None:
        try:
            await self.handle_message(msg)
        except Exception:
            logger.exception("wecom handle_message failed")

    async def handle_message(self, msg: dict[str, Any]) -> None:
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

        text = (reply or "").strip() or "（无回复内容）"
        # 表单场景简单提示（MVP 无 A2UI）
        if "【人机" in text or "请到" in text:
            pass
        max_chars = self.config.max_reply_chars
        if len(text) > max_chars:
            text = (
                text[: max_chars - 40]
                + f"\n\n…(已截断)\n完整记录 session：`{session_id}`"
            )
        else:
            # 短注：可在网页用同一 session 查看
            if len(text) < max_chars - 80:
                text = f"{text}\n\n——\n会话 `{session_id}`（网页历史可查）"
        await self._push(userid, text)

    async def _push(self, userid: str, content: str) -> None:
        try:
            await self.client.send_markdown(userid=userid, content=content)
        except Exception:
            # markdown 失败再试 text
            logger.warning("wecom markdown send failed, fallback text")
            await self.client.send_text(userid=userid, content=content)


async def run_agent_via_runtime(
    message: str,
    *,
    session_id: str,
    bearer_token: str,
    runtime: Any,
    run_lock: asyncio.Lock,
) -> str:
    """供示例站注入：持锁跑一轮 Runtime，返回 Respond 正文。"""
    async with run_lock:
        try:
            final: RunResult | None = None
            async for item in runtime.run_stream(
                Message(role=Role.USER, content=message),
                session_id=session_id,
                present_mode="markdown",
                bearer_token=bearer_token,
                trigger_source="user",
            ):
                if isinstance(item, RunResult):
                    final = item
            if final is None:
                raise RuntimeError("未收到编排结果")
            if not final.ok:
                raise RuntimeError(final.error or "运行失败")
            content = (final.content or "").strip()
            # 若本轮产生了 A2UI 等待，提示去网页
            if final.a2ui_messages or (
                final.answer_parts
                and any(
                    isinstance(p, dict) and p.get("type") == "a2ui"
                    for p in final.answer_parts
                )
            ):
                tip = (
                    f"\n\n（本轮含表单操作，请在 Web 对话页打开会话 "
                    f"`{session_id}` 完成填写。）"
                )
                content = (content + tip).strip()
            return content
        finally:
            clear_request_context()
