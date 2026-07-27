"""企业微信：加解密、换 Token、MsgId 排重、adapter。"""

from __future__ import annotations

import asyncio
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest

from im.wecom.adapter import MsgIdDeduper, WeComChatAdapter
from im.wecom.client import WeComAppClient
from im.wecom.crypto import WeComCrypto, WeComCryptoError, parse_message_xml
from im.wecom.token_resolve import (
    BusinessTokenResolver,
    TokenResolveConfig,
    TokenResolveError,
)

# 官方文档加解密示例
_CORP_ID = "wx5823bf96d3bd56c7"
_TOKEN = "QDG6eK"
_AES_KEY = "jWmYm7qr5nMoAUwZRjGtBxmz3KA1tkAj3ykkR6q2B2C"
_ENCRYPT = (
    "RypEvHKD8QQKFhvQ6QleEB4J58tiPdvo+rtK1I9qca6aM/wvqnLSV5zEPeusUiX5L5X/"
    "0lWfrf0QADHHhGd3QczcdCUpj911L3vg3W/sYYvuJTs3TUUkSUXxaccAS0qhxchrRYt66wiSpG"
    "LYL42aM6A8dTT+6k4aSknmPj48kzJs8qLjvd4Xgpue06DOdnLxAUHzM6+kDZ+HMZfJYuR+Ltw"
    "Gc2hgf5gsijff0ekUNXZiqATP7PF5mZxZ3Izoun1s4zG4LUMnvw2r+KqCKIw+3IQH03v+BCA9"
    "nMELNqbSf6tiWSrXJB3LAVGUcallcrw8V2t9EL4EhzJWrQUax5wLVMNS0+rUPA3k22Ncx4XXZ"
    "S9o0MBH27Bo6BpNelZpS+/uh9KsNlY6bHCmJU9p8g7m3fVKn28H3KDYA5Pl/T8Z1ptDAVe0lX"
    "dQ2YoyyH2uyPIGHBZZIs2pDBS8R07+qN+E7Q=="
)
_MSG_SIGNATURE = "477715d11cdb4164915debcba66cb864d751f3e6"
_TIMESTAMP = "1409659813"
_NONCE = "1372623149"


def test_wecom_crypto_official_vector() -> None:
    crypto = WeComCrypto(_TOKEN, _AES_KEY, _CORP_ID)
    crypto.verify_signature(_MSG_SIGNATURE, _TIMESTAMP, _NONCE, _ENCRYPT)
    plain = crypto.decrypt(_ENCRYPT)
    assert "<MsgType><![CDATA[text]]></MsgType>" in plain
    assert "<Content><![CDATA[hello]]></Content>" in plain
    msg = parse_message_xml(plain)
    assert msg["FromUserName"] == "mycreate"
    assert msg["Content"] == "hello"


def test_wecom_crypto_roundtrip() -> None:
    crypto = WeComCrypto(_TOKEN, _AES_KEY, _CORP_ID)
    xml = (
        "<xml><ToUserName><![CDATA[to]]></ToUserName>"
        "<FromUserName><![CDATA[u1]]></FromUserName>"
        "<MsgType><![CDATA[text]]></MsgType>"
        "<Content><![CDATA[ping]]></Content>"
        "<MsgId>123</MsgId></xml>"
    )
    enc = crypto.encrypt(xml)
    assert crypto.decrypt(enc) == xml


def test_wecom_crypto_bad_signature() -> None:
    crypto = WeComCrypto(_TOKEN, _AES_KEY, _CORP_ID)
    with pytest.raises(WeComCryptoError, match="msg_signature"):
        crypto.verify_signature("deadbeef", _TIMESTAMP, _NONCE, _ENCRYPT)


def test_msgid_deduper() -> None:
    async def _run() -> None:
        d = MsgIdDeduper(max_size=3)
        assert await d.seen_or_add("a") is False
        assert await d.seen_or_add("a") is True
        assert await d.seen_or_add("b") is False
        assert await d.seen_or_add("c") is False
        assert await d.seen_or_add("d") is False
        # a 被挤出后可再登记
        assert await d.seen_or_add("a") is False

    asyncio.run(_run())


def test_token_resolve_success() -> None:
    async def _run() -> None:
        cfg = TokenResolveConfig(
            url="https://biz.example/token",
            method="POST",
            body_template='{"wecomUserId":"{wecom_userid}"}',
            token_path="accessToken",
        )
        resolver = BusinessTokenResolver(cfg)

        def handler(request: httpx.Request) -> httpx.Response:
            assert b"wecomUserId" in request.content
            assert b"zhangsan" in request.content
            return httpx.Response(200, json={"accessToken": "tok-xyz"})

        transport = httpx.MockTransport(handler)
        # 临时注入：直接测 _extract 路径用 mock client 较难；改用 monkeypatch execute
        original = httpx.AsyncClient

        class _Client(original):  # type: ignore[misc,valid-type]
            def __init__(self, *a: Any, **k: Any) -> None:
                k["transport"] = transport
                super().__init__(*a, **k)

        import im.wecom.token_resolve as tr

        old = tr.httpx.AsyncClient
        tr.httpx.AsyncClient = _Client  # type: ignore[misc]
        try:
            token = await resolver.resolve("zhangsan")
            assert token == "tok-xyz"
        finally:
            tr.httpx.AsyncClient = old  # type: ignore[misc]

    asyncio.run(_run())


def test_token_resolve_unbound_404() -> None:
    async def _run() -> None:
        cfg = TokenResolveConfig(url="https://biz.example/token")
        resolver = BusinessTokenResolver(cfg)

        def handler(_request: httpx.Request) -> httpx.Response:
            return httpx.Response(404, json={"message": "not bound"})

        transport = httpx.MockTransport(handler)
        import im.wecom.token_resolve as tr

        class _Client(httpx.AsyncClient):
            def __init__(self, *a: Any, **k: Any) -> None:
                k["transport"] = transport
                super().__init__(*a, **k)

        old = tr.httpx.AsyncClient
        tr.httpx.AsyncClient = _Client  # type: ignore[misc]
        try:
            with pytest.raises(TokenResolveError) as ei:
                await resolver.resolve("nobody")
            assert ei.value.unbound is True
        finally:
            tr.httpx.AsyncClient = old  # type: ignore[misc]

    asyncio.run(_run())


def test_adapter_text_flow() -> None:
    async def _run() -> None:
        crypto = WeComCrypto(_TOKEN, _AES_KEY, _CORP_ID)
        client = MagicMock(spec=WeComAppClient)
        client.send_markdown = AsyncMock(return_value={"errcode": 0})
        client.send_text = AsyncMock(return_value={"errcode": 0})

        resolver = MagicMock()
        resolver.resolve = AsyncMock(return_value="biz-token")

        async def fake_agent(
            message: str, *, session_id: str, bearer_token: str
        ) -> str:
            assert message == "列出钥匙柜"
            assert session_id == "wecom:u1"
            assert bearer_token == "biz-token"
            return "## 结果\n- 柜 A"

        adapter = WeComChatAdapter(
            crypto=crypto,
            client=client,
            token_resolver=resolver,
            run_agent=fake_agent,
        )
        await adapter.handle_message(
            {
                "MsgType": "text",
                "FromUserName": "u1",
                "Content": "列出钥匙柜",
                "MsgId": "m-1",
            }
        )
        client.send_markdown.assert_awaited()
        args = client.send_markdown.await_args
        assert args.kwargs["userid"] == "u1"
        assert "柜 A" in args.kwargs["content"]
        assert "wecom:u1" in args.kwargs["content"]

        # 同 MsgId 不双跑
        resolver.resolve.reset_mock()
        await adapter.handle_message(
            {
                "MsgType": "text",
                "FromUserName": "u1",
                "Content": "列出钥匙柜",
                "MsgId": "m-1",
            }
        )
        resolver.resolve.assert_not_awaited()

    asyncio.run(_run())


def test_adapter_unbound_does_not_run_agent() -> None:
    async def _run() -> None:
        crypto = WeComCrypto(_TOKEN, _AES_KEY, _CORP_ID)
        client = MagicMock(spec=WeComAppClient)
        client.send_markdown = AsyncMock(return_value={"errcode": 0})
        client.send_text = AsyncMock(return_value={"errcode": 0})
        resolver = MagicMock()
        resolver.resolve = AsyncMock(
            side_effect=TokenResolveError("未绑定", unbound=True)
        )
        run_agent = AsyncMock()

        adapter = WeComChatAdapter(
            crypto=crypto,
            client=client,
            token_resolver=resolver,
            run_agent=run_agent,
        )
        await adapter.handle_message(
            {
                "MsgType": "text",
                "FromUserName": "u2",
                "Content": "hi",
                "MsgId": "m-2",
            }
        )
        run_agent.assert_not_awaited()
        client.send_markdown.assert_awaited()
        assert "未绑定" in client.send_markdown.await_args.kwargs["content"]

    asyncio.run(_run())


def test_adapter_non_text() -> None:
    async def _run() -> None:
        crypto = WeComCrypto(_TOKEN, _AES_KEY, _CORP_ID)
        client = MagicMock(spec=WeComAppClient)
        client.send_markdown = AsyncMock(return_value={"errcode": 0})
        client.send_text = AsyncMock(return_value={"errcode": 0})
        adapter = WeComChatAdapter(
            crypto=crypto,
            client=client,
            token_resolver=MagicMock(),
            run_agent=AsyncMock(),
        )
        await adapter.handle_message(
            {
                "MsgType": "image",
                "FromUserName": "u3",
                "MsgId": "m-3",
            }
        )
        assert "文字" in client.send_markdown.await_args.kwargs["content"]

    asyncio.run(_run())
