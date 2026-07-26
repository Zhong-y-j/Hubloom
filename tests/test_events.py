"""事件入站：契约、Skill 分册目录、幂等、鉴权。"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any, AsyncIterator
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import HTTPException
from starlette.requests import Request

from agent.run import RunResult
from events.catalog import (
    EventCatalog,
    apply_template,
    render_event_trigger,
    resolve_events_skill_dir,
)
from events.dispatcher import EventDispatcher
from events.idempotency import EventDispatchResult, IdempotencyStore
from events.models import HubloomEvent, normalize_event

_REPO_ROOT = Path(__file__).resolve().parents[1]
_EVENTS_DIR = _REPO_ROOT / "skills" / "events"


def _repo_catalog(
    config_catalog: dict[str, Any] | None = None,
) -> EventCatalog:
    return EventCatalog.load(
        events_dir=_EVENTS_DIR,
        config_catalog=config_catalog,
    )


def test_normalize_event_requires_core_fields() -> None:
    with pytest.raises(ValueError, match="event_id"):
        normalize_event({"type": "locker.offline", "session_id": "s1"})
    with pytest.raises(ValueError, match="type"):
        normalize_event({"event_id": "e1", "session_id": "s1"})
    with pytest.raises(ValueError, match="session_id"):
        normalize_event({"event_id": "e1", "type": "locker.offline"})

    ev = normalize_event(
        {
            "event_id": "e1",
            "type": "locker.offline",
            "session_id": "ops-1",
            "payload": {"deviceId": "D-9"},
            "instruction": "  自定义  ",
        }
    )
    assert ev.event_id == "e1"
    assert ev.session_id == "ops-1"
    assert ev.payload["deviceId"] == "D-9"
    assert ev.instruction == "自定义"


def test_catalog_scans_skills_events_playbooks() -> None:
    catalog = _repo_catalog()
    types = catalog.types()
    assert "locker.created" in types
    assert "locker.offline" in types
    assert "order.refund" in types

    rows = {r["type"]: r for r in catalog.list_types()}
    assert rows["locker.created"]["playbook_file"] == "locker-created.md"
    assert rows["order.refund"]["skill_id"] == "events"


def test_catalog_renders_locker_offline() -> None:
    catalog = _repo_catalog()
    entry = catalog.get("locker.offline")
    event = HubloomEvent(
        event_id="evt-1",
        type="locker.offline",
        session_id="s1",
        payload={
            "deviceId": "CAB-001",
            "gatedCommunityName": "阳光",
            "cabinetName": "东门柜",
        },
    )
    text = render_event_trigger(event, entry)
    assert "【事件 · locker.offline" in text
    assert "【事件处理规程" in text
    assert "CAB-001" in text
    assert "本轮由业务事件触发" in text
    assert "离线诊断" in text or "locker.offline" in text

    filled = apply_template(entry.playbook, event=event, entry=entry)
    assert "deviceId" in entry.payload_fields


def test_catalog_unknown_type() -> None:
    catalog = _repo_catalog()
    with pytest.raises(KeyError, match="未配置"):
        catalog.get("no.such.event")


def test_catalog_config_override() -> None:
    catalog = _repo_catalog(
        {
            "locker.offline": {
                "title": "柜机掉线",
                "instruction_template": "查一下 {payload.deviceId}",
            }
        }
    )
    entry = catalog.get("locker.offline")
    assert entry.title == "柜机掉线"
    event = HubloomEvent(
        event_id="e",
        type="locker.offline",
        session_id="s",
        payload={"deviceId": "X"},
    )
    assert "查一下 X" in render_event_trigger(event, entry)


def test_catalog_scan_temp_playbook(tmp_path: Path) -> None:
    (tmp_path / "only-a.md").write_text(
        "---\nevent: demo.a\ntitle: A\npayload_fields: [id]\n---\n\n# do A\n",
        encoding="utf-8",
    )
    (tmp_path / "SKILL.md").write_text(
        "---\nname: events\ndescription: x\n---\n\n# skip\n",
        encoding="utf-8",
    )
    catalog = EventCatalog.load(events_dir=tmp_path)
    assert catalog.types() == ["demo.a"]
    assert catalog.get("demo.a").playbook_file == "only-a.md"


def test_resolve_events_skill_dir() -> None:
    path = resolve_events_skill_dir(
        skills_dir="skills",
        source_path=str(_REPO_ROOT / "config" / "env.example.yaml"),
    )
    assert path == _EVENTS_DIR.resolve()


def test_idempotency_store_put_get() -> None:
    store = IdempotencyStore()
    result = EventDispatchResult(
        event_id="e1",
        session_id="s1",
        type="locker.offline",
        ok=True,
        summary="done",
    )
    store.put(result)
    got = store.get("e1")
    assert got is not None
    assert got.summary == "done"


def test_dispatcher_idempotent_and_trigger_source() -> None:
    async def _run() -> None:
        catalog = _repo_catalog()
        dispatcher = EventDispatcher(catalog=catalog, present_mode="markdown")
        calls: list[dict[str, Any]] = []

        async def fake_run_stream(
            trigger: Any,
            *,
            session_id: str,
            present_mode: str | None = None,
            bearer_token: str | None = None,
            trigger_source: str = "user",
            max_think_rounds: int | None = None,
        ) -> AsyncIterator[Any]:
            calls.append(
                {
                    "content": getattr(trigger, "content", ""),
                    "session_id": session_id,
                    "trigger_source": trigger_source,
                    "bearer_token": bearer_token,
                    "present_mode": present_mode,
                }
            )
            yield RunResult(content="已核查，建议重启", ok=True, think_rounds=2)

        runtime = MagicMock()
        runtime.run_stream = fake_run_stream
        dispatcher.bind_runtime(runtime)

        event = HubloomEvent(
            event_id="same-id",
            type="locker.offline",
            session_id="ops-session",
            payload={"deviceId": "D1"},
            bearer_token="tok-1",
        )
        r1 = await dispatcher.dispatch(event)
        assert r1.ok and not r1.duplicate
        assert r1.summary == "已核查，建议重启"
        assert len(calls) == 1
        assert calls[0]["trigger_source"] == "event"
        assert calls[0]["bearer_token"] == "tok-1"
        assert "【事件 · locker.offline" in calls[0]["content"]
        assert "【事件处理规程" in calls[0]["content"]

        r2 = await dispatcher.dispatch(event)
        assert r2.duplicate and r2.ok
        assert len(calls) == 1

    asyncio.run(_run())


def test_dispatcher_rejects_unknown_type() -> None:
    async def _run() -> None:
        dispatcher = EventDispatcher(catalog=_repo_catalog())
        dispatcher.bind_runtime(MagicMock())
        with pytest.raises(ValueError, match="未配置"):
            await dispatcher.dispatch(
                HubloomEvent(
                    event_id="e",
                    type="no.such",
                    session_id="s",
                )
            )

    asyncio.run(_run())


def test_dispatcher_requires_payload_fields() -> None:
    async def _run() -> None:
        dispatcher = EventDispatcher(catalog=_repo_catalog())
        dispatcher.bind_runtime(MagicMock())
        with pytest.raises(ValueError, match="deviceId"):
            await dispatcher.dispatch(
                HubloomEvent(
                    event_id="e",
                    type="locker.offline",
                    session_id="s",
                    payload={},
                )
            )

    asyncio.run(_run())


def _make_json_request(payload: dict[str, Any]) -> Request:
    body = json.dumps(payload).encode("utf-8")

    async def receive() -> dict[str, Any]:
        return {"type": "http.request", "body": body, "more_body": False}

    scope = {
        "type": "http",
        "asgi": {"version": "3.0"},
        "http_version": "1.1",
        "method": "POST",
        "scheme": "http",
        "path": "/v1/events",
        "raw_path": b"/v1/events",
        "query_string": b"",
        "headers": [(b"content-type", b"application/json")],
        "client": ("127.0.0.1", 123),
        "server": ("test", 80),
    }
    return Request(scope, receive)


def test_event_ingest_endpoint_auth_and_enable() -> None:
    from examples.chat import app as chat_app

    runtime = MagicMock()
    runtime.cfg.events_enable = False
    runtime.cfg.events_shared_secret = "s3cret"
    dispatcher = MagicMock()
    dispatcher.dispatch = AsyncMock(
        return_value=EventDispatchResult(
            event_id="e1",
            session_id="s1",
            type="locker.offline",
            ok=True,
            summary="done",
        )
    )
    dispatcher.catalog = _repo_catalog()
    chat_app._runtime = runtime
    chat_app._dispatcher = dispatcher

    payload = {
        "event_id": "e1",
        "type": "locker.offline",
        "session_id": "s1",
        "payload": {"deviceId": "D1"},
    }

    async def _run() -> None:
        with pytest.raises(HTTPException) as disabled:
            await chat_app.ingest_event(
                _make_json_request(payload),
                x_event_secret="s3cret",
            )
        assert disabled.value.status_code == 503

        runtime.cfg.events_enable = True
        with pytest.raises(HTTPException) as unauthorized:
            await chat_app.ingest_event(
                _make_json_request(payload),
                x_event_secret=None,
            )
        assert unauthorized.value.status_code == 401

        ok = await chat_app.ingest_event(
            _make_json_request(payload),
            x_event_secret="s3cret",
        )
        assert ok.ok is True
        assert ok.event_id == "e1"
        dispatcher.dispatch.assert_awaited()

        types_resp = await chat_app.list_event_types(x_event_secret="s3cret")
        assert types_resp["total"] >= 3
        assert any(t["type"] == "locker.created" for t in types_resp["types"])

        dispatcher.dispatch = AsyncMock(
            side_effect=ValueError("未配置的事件类型: 'unknown.type'")
        )
        with pytest.raises(HTTPException) as unknown:
            await chat_app.ingest_event(
                _make_json_request({**payload, "type": "unknown.type"}),
                x_event_secret="s3cret",
            )
        assert unknown.value.status_code == 400

    try:
        asyncio.run(_run())
    finally:
        chat_app._runtime = None
        chat_app._dispatcher = None


def test_concurrent_same_event_id_runs_once() -> None:
    async def _run() -> None:
        catalog = _repo_catalog()
        dispatcher = EventDispatcher(catalog=catalog)
        started = asyncio.Event()
        release = asyncio.Event()
        calls = 0

        async def slow_run_stream(*_a: Any, **_kw: Any) -> AsyncIterator[Any]:
            nonlocal calls
            calls += 1
            started.set()
            await release.wait()
            yield RunResult(content="once", ok=True)

        runtime = MagicMock()
        runtime.run_stream = slow_run_stream
        dispatcher.bind_runtime(runtime)

        event = HubloomEvent(
            event_id="race-1",
            type="locker.created",
            session_id="s",
            payload={"deviceId": "KC-1"},
        )

        t1 = asyncio.create_task(dispatcher.dispatch(event))
        await started.wait()
        t2 = asyncio.create_task(dispatcher.dispatch(event))
        await asyncio.sleep(0.05)
        release.set()
        r1, r2 = await asyncio.gather(t1, t2)
        assert calls == 1
        assert sorted([r1.duplicate, r2.duplicate]) == [False, True]
        assert {r1.summary, r2.summary} == {"once"}

    asyncio.run(_run())
