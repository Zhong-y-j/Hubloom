"""Serve Events / 企微回调冒烟（不打真 LLM / 真企微）。

用法::

    PYTHONPATH=src .venv/bin/python -m pytest tests/test_hubloom_serve_events_wecom.py -q
"""

from __future__ import annotations

import tempfile
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

from fastapi.testclient import TestClient

from agent.run import RunResult
from config import HubloomConfig
from events.catalog import EventCatalog
from events.dispatcher import EventDispatcher
from events.idempotency import create_idempotency_store
from events.session_gate import create_session_gate
from im.wecom.adapter import WeComAdapterConfig, WeComChatAdapter
from memory.store import create_conversation_store
from redis_test_utils import make_fake_session_backends
from runtime import HubloomRuntime
from server.app import create_app
from tools.base import BaseTool


class _EchoTool(BaseTool):
    name = "echo_pet"
    description = "x"
    parameters = {"type": "object", "properties": {}}

    async def execute(self, **kwargs: Any) -> str:
        del kwargs
        return "ok"


class _FakeEventAgent:
    def __init__(self) -> None:
        self.calls = 0

    async def run_event_turn(self, trigger, **kwargs) -> RunResult:
        del trigger, kwargs
        self.calls += 1
        return RunResult(
            ok=True,
            status="completed",
            content=f"fake-ok:{self.calls}",
            think_rounds=1,
        )


def _fake_redis():
    from fakeredis.aioredis import FakeRedis

    return FakeRedis(decode_responses=True)


def _make_runtime(*, events_enable: bool = False, wecom_enable: bool = False) -> HubloomRuntime:
    tmp = Path(tempfile.mkdtemp())
    cfg = HubloomConfig(
        openai_api_key="x",
        enable_mcp=False,
        memory_db_path=str(tmp / "m.db"),
        events_enable=events_enable,
        events_shared_secret="secret-test",
        wecom_enable=wecom_enable,
        wecom_max_reply_chars=650,
        agent_log=False,
        redis_url="redis://localhost:6379/0",
        skills_dir="skills",
    )
    store, lock = make_fake_session_backends()
    conv = create_conversation_store(backend="sqlite", db_path=str(tmp / "m.db"))
    return HubloomRuntime(
        cfg=cfg,
        llm=MagicMock(),
        system_before="t",
        system_after="t",
        mcp_setup=None,
        _mcp_tools=[_EchoTool()],
        session_store=store,
        session_lock=lock,
        conversation_store=conv,
    )


def _make_dispatcher(agent: _FakeEventAgent) -> EventDispatcher:
    redis = _fake_redis()
    catalog = EventCatalog.load(events_dir="skills/events")
    d = EventDispatcher(
        catalog=catalog,
        idempotency=create_idempotency_store(
            redis_url="redis://localhost:6379/0",
            redis=redis,
        ),
        session_gate=create_session_gate(
            redis_url="redis://localhost:6379/0",
            redis=redis,
        ),
        wait_profile="no_wait",
    )
    d.bind_agent(agent)
    return d


def test_events_disabled_returns_503() -> None:
    rt = _make_runtime(events_enable=False)
    app = create_app(runtime=rt)
    with TestClient(app) as client:
        r = client.post(
            "/v1/events",
            json={
                "event_id": "e1",
                "type": "locker.created",
                "session_id": "s1",
                "payload": {"deviceId": "D1"},
            },
        )
        assert r.status_code == 503


def test_events_ingest_and_idempotent() -> None:
    agent = _FakeEventAgent()
    rt = _make_runtime(events_enable=True)
    dispatcher = _make_dispatcher(agent)
    app = create_app(runtime=rt, event_dispatcher=dispatcher)
    body = {
        "event_id": "evt-serve-1",
        "type": "locker.created",
        "session_id": "sess-e1",
        "payload": {"deviceId": "LK-1"},
    }
    headers = {"X-Event-Secret": "secret-test"}
    with TestClient(app) as client:
        h = client.get("/health")
        assert h.status_code == 200
        assert h.json()["events_enabled"] is True

        types = client.get("/v1/events/types", headers=headers)
        assert types.status_code == 200
        assert types.json()["total"] >= 1

        bad = client.post("/v1/events", json=body, headers={"X-Event-Secret": "wrong"})
        assert bad.status_code == 401

        r1 = client.post("/v1/events", json=body, headers=headers)
        assert r1.status_code == 200
        data1 = r1.json()
        assert data1["ok"] is True
        assert data1["duplicate"] is False
        assert agent.calls == 1

        r2 = client.post("/v1/events", json=body, headers=headers)
        assert r2.status_code == 200
        data2 = r2.json()
        assert data2["duplicate"] is True
        assert agent.calls == 1


def test_wecom_disabled_returns_503() -> None:
    rt = _make_runtime(wecom_enable=False)
    app = create_app(runtime=rt)
    with TestClient(app) as client:
        r = client.get(
            "/v1/im/wecom/callback",
            params={
                "msg_signature": "x",
                "timestamp": "1",
                "nonce": "n",
                "echostr": "e",
            },
        )
        assert r.status_code == 503


def test_wecom_callback_ack_and_schedule() -> None:
    rt = _make_runtime(wecom_enable=True)
    scheduled: list[dict] = []

    crypto = MagicMock()
    crypto.verify_url.return_value = "echo-ok"
    crypto.decrypt_message.return_value = "<xml></xml>"

    adapter = WeComChatAdapter(
        crypto=crypto,
        client=MagicMock(),
        token_resolver=MagicMock(),
        run_agent=MagicMock(),
        config=WeComAdapterConfig(max_reply_chars=650),
    )

    def _ack(**kwargs):
        del kwargs
        msg = {
            "MsgType": "text",
            "FromUserName": "u1",
            "Content": "hi",
            "MsgId": "m1",
        }
        return "", msg

    adapter.handle_callback_sync_ack = _ack  # type: ignore[method-assign]
    adapter.schedule_handle_message = lambda msg: scheduled.append(msg)  # type: ignore[method-assign]

    app = create_app(runtime=rt, wecom_adapter=adapter)
    with TestClient(app) as client:
        h = client.get("/health")
        assert h.json()["wecom_enabled"] is True

        v = client.get(
            "/v1/im/wecom/callback",
            params={
                "msg_signature": "s",
                "timestamp": "1",
                "nonce": "n",
                "echostr": "enc",
            },
        )
        assert v.status_code == 200
        assert v.text == "echo-ok"

        p = client.post(
            "/v1/im/wecom/callback",
            params={
                "msg_signature": "s",
                "timestamp": "1",
                "nonce": "n",
            },
            content=b"<xml>enc</xml>",
        )
        assert p.status_code == 200
        assert p.content == b""
        assert len(scheduled) == 1
        assert scheduled[0]["Content"] == "hi"


def test_wecom_format_reply_short() -> None:
    adapter = WeComChatAdapter(
        crypto=MagicMock(),
        client=MagicMock(),
        token_resolver=MagicMock(),
        run_agent=MagicMock(),
        config=WeComAdapterConfig(max_reply_chars=80),
    )
    long = "结论：" + ("很长" * 40)
    out = adapter._format_reply(long, "wecom:u1")
    assert len(out) <= 120
    assert "已截断" in out
    assert "网页会话" not in out
