"""Hubloom Serve API 冒烟（注入假 Runtime，不需真 LLM / 示例站）。

用法::

    PYTHONPATH=src .venv/bin/python tests/test_hubloom_serve.py
"""

from __future__ import annotations

import asyncio
import tempfile
from collections.abc import AsyncIterator, Sequence
from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient

from agent.actions import CONTROL_ASK, CONTROL_FINISH
from agent.policy import Playbook
from redis_test_utils import make_fake_session_backends
from config import HubloomConfig
from core.models import LLMOutput, Message, Role, StopReason, ToolCall
from core.provider import LLMProvider, LLMStreamEvent, StreamEndEvent
from runtime import HubloomRuntime
from server.app import create_app
from tools.base import BaseTool


class ScriptedLLM(LLMProvider):
    def __init__(self, outputs: Sequence[LLMOutput]) -> None:
        self._outputs = list(outputs)
        self._i = 0

    def extend(self, outputs: Sequence[LLMOutput]) -> None:
        self._outputs.extend(outputs)

    async def generate(self, messages, tools=None, stop=None, **kwargs):
        async for ev in self.generate_stream(messages, tools=tools, stop=stop, **kwargs):
            if isinstance(ev, StreamEndEvent):
                return ev.output
        raise RuntimeError("no output")

    async def generate_stream(
        self, messages, tools=None, stop=None, **kwargs
    ) -> AsyncIterator[LLMStreamEvent]:
        del messages, tools, stop, kwargs
        if self._i >= len(self._outputs):
            raise RuntimeError("exhausted")
        out = self._outputs[self._i]
        self._i += 1
        yield StreamEndEvent(out)


class EchoPetTool(BaseTool):
    name = "echo_pet"
    description = "登记"
    parameters = {
        "type": "object",
        "properties": {"name": {"type": "string"}},
        "required": ["name"],
    }

    async def execute(self, **kwargs: Any) -> str:
        return f"registered:{kwargs.get('name', '')}"


def _out(*calls: ToolCall) -> LLMOutput:
    return LLMOutput(
        content="",
        tool_calls=list(calls),
        stop_reason=StopReason.TOOL_CALLS,
    )


def _tc(oid: str, name: str, args: dict | None = None) -> ToolCall:
    return ToolCall(id=oid, name=name, arguments=args or {})


def _make_runtime(llm: ScriptedLLM, memory_db: Path) -> HubloomRuntime:
    cfg = HubloomConfig(
        openai_api_key="x",
        enable_mcp=False,
        memory_db_path=str(memory_db),
        default_wait_profile="interactive",
        agent_log=False,
        redis_url="redis://localhost:6379/0",
    )
    store, lock = make_fake_session_backends()
    return HubloomRuntime(
        cfg=cfg,
        llm=llm,
        system_before="serve test",
        system_after="serve test",
        mcp_setup=None,
        _mcp_tools=[EchoPetTool()],
        playbook=Playbook(),
        session_store=store,
        session_lock=lock,
        default_wait_profile="interactive",
    )


def test_cli_help() -> None:
    from server.cli import main

    try:
        main(["serve", "--help"])
    except SystemExit as exc:
        assert exc.code in (0, None)
    print("ok: hubloom serve --help")


def test_health_and_chat_resume_sse() -> None:
    tmp = Path(tempfile.mkdtemp())
    llm = ScriptedLLM(
        [_out(_tc("q1", CONTROL_ASK, {"question": "叫什么名字？"}))]
    )
    rt = _make_runtime(llm, tmp / "m.db")
    app = create_app(runtime=rt)
    headers = {
        "X-MCP-Token": "test-token",
        "X-Session-Id": "serve-demo",
    }

    with TestClient(app) as client:
        h = client.get("/health")
        assert h.status_code == 200 and h.json()["status"] == "ok"

        # interactive ask → awaiting_user
        with client.stream(
            "POST",
            "/v1/chat",
            headers=headers,
            json={
                "message": "加一只宠物",
                "session_id": "serve-demo",
                "stream": True,
                "wait_profile": "interactive",
            },
        ) as resp:
            assert resp.status_code == 200
            body = "".join(resp.iter_text())
        assert "event: awaiting_user" in body
        assert "event: run_result" in body
        assert "叫什么" in body or "名字" in body

        await_token = ""
        await_run_id = ""
        import json as _json

        for block in body.split("\n\n"):
            if not block.strip().startswith("event: awaiting_user"):
                # event line may not be first if blank; check containment
                if "event: awaiting_user" not in block:
                    continue
            for line in block.splitlines():
                if line.startswith("data:"):
                    data = _json.loads(line[5:].strip())
                    await_token = data["await_token"]
                    await_run_id = data["await_run_id"]
        assert await_token and await_run_id

        llm.extend(
            [
                _out(_tc("a1", "echo_pet", {"name": "小花"})),
                _out(
                    _tc(
                        "f1",
                        CONTROL_FINISH,
                        {"summary": "已登记小花"},
                    )
                ),
            ]
        )
        with client.stream(
            "POST",
            "/v1/chat/resume",
            headers=headers,
            json={
                "session_id": "serve-demo",
                "user_reply": "小花",
                "run_id": await_run_id,
                "await_token": await_token,
                "stream": True,
            },
        ) as resp:
            assert resp.status_code == 200
            body2 = "".join(resp.iter_text())
        assert "event: tool_result" in body2
        assert "registered:小花" in body2
        assert "event: run_result" in body2
        assert "已登记" in body2

        hist = client.get(
            "/v1/chat/history",
            params={"session_id": "serve-demo"},
        )
        assert hist.status_code == 200
        assert hist.json()["total"] >= 2

    print("ok: /health + /v1/chat + /v1/chat/resume SSE")


def main() -> None:
    test_cli_help()
    test_health_and_chat_resume_sse()
    print("\nhubloom serve: 全部通过")


if __name__ == "__main__":
    main()
