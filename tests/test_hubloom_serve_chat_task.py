"""联调：对已启动的 Hubloom Serve 打真实 /v1/chat（走真 LLM）。

本文件**不是** ScriptedLLM 冒烟。请先启动服务，再跑本脚本。

启动服务（另开终端）::

    PYTHONPATH=src .venv/bin/python -m server serve --config config/env.yaml

再测::

    PYTHONPATH=src .venv/bin/python tests/test_hubloom_serve_chat_task.py

可选环境变量::

    HUBLOOM_SERVE_URL=http://127.0.0.1:8765
    HUBLOOM_MCP_TOKEN=你的业务Bearer
    HUBLOOM_SESSION_ID=live-chat-demo
    HUBLOOM_CHAT_MESSAGE=请用一句话介绍你自己
    HUBLOOM_SSE_VERBOSE=1          # 逐条打印 thought_delta 碎片
"""

from __future__ import annotations

import json
import os
import sys
import uuid
from typing import Any

import httpx

DEFAULT_BASE = "http://127.0.0.1:8765"


def _base() -> str:
    return (os.environ.get("HUBLOOM_SERVE_URL") or DEFAULT_BASE).rstrip("/")


def _token() -> str:
    return (os.environ.get("HUBLOOM_MCP_TOKEN") or "").strip()


def _session_id() -> str:
    return (
        os.environ.get("HUBLOOM_SESSION_ID") or f"live-chat-{uuid.uuid4().hex[:8]}"
    ).strip()


def _headers(session_id: str) -> dict[str, str]:
    h = {
        "Content-Type": "application/json",
        "X-Session-Id": session_id,
        "Accept": "text/event-stream",
    }
    token = _token()
    if token:
        h["X-MCP-Token"] = token
        h["Authorization"] = f"Bearer {token}"
    return h


def _fail(msg: str) -> None:
    print(f"\n失败: {msg}", file=sys.stderr)
    print(
        "\n请先启动 Hubloom Serve，例如：\n"
        "  PYTHONPATH=src .venv/bin/python -m server serve --config config/env.yaml\n"
        "再设置 Token（若 mcp.enable=true）：\n"
        "  export HUBLOOM_MCP_TOKEN=...\n"
        f"当前目标: {_base()}",
        file=sys.stderr,
    )
    raise SystemExit(1)


def check_health(client: httpx.Client) -> None:
    try:
        r = client.get(f"{_base()}/health", timeout=5.0)
    except httpx.ConnectError:
        _fail(f"连不上 {_base()}/health（服务未启动？）")
    if r.status_code != 200:
        _fail(f"/health HTTP {r.status_code}: {r.text}")
    data = r.json()
    if data.get("status") != "ok":
        _fail(f"/health 异常: {data}")
    print(f"ok: GET /health → {data}")


def check_mcp(client: httpx.Client) -> dict[str, Any]:
    r = client.get(f"{_base()}/v1/mcp/status", timeout=10.0)
    if r.status_code != 200:
        print(f"warn: /v1/mcp/status HTTP {r.status_code}")
        return {}
    data = r.json()
    print(
        f"ok: GET /v1/mcp/status → ready={data.get('mcp_ready')} "
        f"tools={data.get('tool_count')} status={data.get('status')}"
    )
    return data


def parse_sse(text: str) -> list[tuple[str, dict[str, Any]]]:
    events: list[tuple[str, dict[str, Any]]] = []
    event = ""
    for block in text.split("\n\n"):
        if not block.strip():
            continue
        data_obj: dict[str, Any] | None = None
        for line in block.splitlines():
            if line.startswith("event:"):
                event = line[6:].strip()
            elif line.startswith("data:"):
                raw = line[5:].strip()
                try:
                    data_obj = json.loads(raw)
                except json.JSONDecodeError:
                    data_obj = {"raw": raw}
        if event and data_obj is not None:
            events.append((event, data_obj))
            event = ""
    return events


def _preview(text: str, limit: int = 240) -> str:
    t = (text or "").replace("\n", "\\n")
    if len(t) <= limit:
        return t
    return t[: limit - 1] + "…"


def _print_event_detail(name: str, data: dict[str, Any]) -> None:
    """把关键 SSE 的实际载荷打出来。"""
    if name == "run_started":
        print(
            f"  [{name}] mode={data.get('mode')} "
            f"run_id={data.get('run_id')} session={data.get('session_id')}"
        )
    elif name == "phase":
        print(f"  [{name}] phase={data.get('phase')} route={data.get('route')}")
    elif name == "thought_delta":
        # 流式思考碎片：默认折叠，设 HUBLOOM_SSE_VERBOSE=1 才逐条打
        if (os.environ.get("HUBLOOM_SSE_VERBOSE") or "").strip() in (
            "1",
            "true",
            "yes",
        ):
            print(
                f"  [{name}] phase={data.get('phase')} "
                f"delta={_preview(str(data.get('delta') or ''), 80)!r}"
            )
    elif name == "text_delta":
        print(f"  [{name}] {_preview(str(data.get('delta') or ''), 120)!r}")
    elif name == "step":
        print(
            f"  [{name}] step={data.get('step')} action={data.get('action')} "
            f"journal_ids={data.get('journal_ids')}"
        )
    elif name == "tool_call":
        print(
            f"  [{name}] {data.get('tool_name')} "
            f"args={_preview(json.dumps(data.get('args') or {}, ensure_ascii=False), 160)}"
        )
    elif name == "tool_result":
        print(
            f"  [{name}] {data.get('tool_name')} "
            f"err={data.get('is_error')} "
            f"journal={data.get('journal_id')} "
            f"result={_preview(str(data.get('result') or ''), 200)!r}"
        )
    elif name == "policy_reject":
        print(
            f"  [{name}] code={data.get('code')} fused={data.get('fused')} "
            f"reason={data.get('reason')}"
        )
    elif name == "awaiting_user":
        print(
            f"  [{name}] kind={data.get('kind')} "
            f"prompt={_preview(str(data.get('prompt') or ''), 160)!r} "
            f"token={data.get('await_token')}"
        )
    elif name == "final_answer":
        print(f"  [{name}] {_preview(str(data.get('content') or ''), 300)!r}")
    elif name == "run_stats":
        print(
            f"  [{name}] steps={data.get('steps')} "
            f"tools={data.get('tool_calls')} "
            f"errors={data.get('tool_errors')} "
            f"ms={data.get('elapsed_ms')}"
        )
    elif name == "run_complete":
        print(
            f"  [{name}] status={data.get('status')} ok={data.get('ok')} "
            f"content={_preview(str(data.get('content') or ''), 200)!r}"
        )
    elif name == "run_result":
        print(
            f"  [{name}] status={data.get('status')} ok={data.get('ok')} "
            f"journal={data.get('journal_run_id')} "
            f"content={_preview(str(data.get('content') or ''), 200)!r}"
        )
    elif name == "error":
        print(f"  [{name}] {data.get('error')}")
    elif name == "run_finished":
        print(f"  [{name}] run_id={data.get('run_id')}")
    else:
        print(f"  [{name}] {_preview(json.dumps(data, ensure_ascii=False), 200)}")


def _consume_sse_stream(
    resp: httpx.Response,
) -> tuple[str, list[tuple[str, dict[str, Any]]]]:
    """边收边解析完整 SSE 块，并打印有内容的事件。"""
    buf = ""
    chunks: list[str] = []
    events: list[tuple[str, dict[str, Any]]] = []
    thought_buf: list[str] = []

    for chunk in resp.iter_text():
        chunks.append(chunk)
        buf += chunk
        while "\n\n" in buf:
            block, buf = buf.split("\n\n", 1)
            if not block.strip():
                continue
            event = ""
            data_obj: dict[str, Any] | None = None
            for line in block.splitlines():
                if line.startswith("event:"):
                    event = line[6:].strip()
                elif line.startswith("data:"):
                    try:
                        data_obj = json.loads(line[5:].strip())
                    except json.JSONDecodeError:
                        data_obj = {"raw": line[5:].strip()}
            if not event or data_obj is None:
                continue
            events.append((event, data_obj))
            if event == "thought_delta":
                thought_buf.append(str(data_obj.get("delta") or ""))
                # 实时打出思考增量（同一行滚动感：直接 print delta）
                sys.stdout.write(str(data_obj.get("delta") or ""))
                sys.stdout.flush()
            else:
                if thought_buf:
                    print()  # 结束思考流换行
                    print(
                        f"  [thought 合计 {len(''.join(thought_buf))} 字] "
                        f"{_preview(''.join(thought_buf), 400)!r}"
                    )
                    thought_buf.clear()
                _print_event_detail(event, data_obj)

    if thought_buf:
        print()
        print(
            f"  [thought 合计 {len(''.join(thought_buf))} 字] "
            f"{_preview(''.join(thought_buf), 400)!r}"
        )
    return "".join(chunks), events


def chat_sse(
    client: httpx.Client,
    *,
    message: str,
    session_id: str,
    wait_profile: str | None = None,
    stream: bool = True,
) -> tuple[str, list[tuple[str, dict[str, Any]]], dict[str, Any] | None]:
    """调用 POST /v1/chat；返回 (raw_body, events, run_result|sync_json)。"""
    payload: dict[str, Any] = {
        "message": message,
        "session_id": session_id,
        "stream": stream,
    }
    if wait_profile:
        payload["wait_profile"] = wait_profile

    if not stream:
        r = client.post(
            f"{_base()}/v1/chat",
            headers=_headers(session_id),
            json=payload,
            timeout=180.0,
        )
        if r.status_code >= 400:
            _fail(f"POST /v1/chat sync HTTP {r.status_code}: {r.text}")
        data = r.json()
        return r.text, [], data

    with client.stream(
        "POST",
        f"{_base()}/v1/chat",
        headers=_headers(session_id),
        json=payload,
        timeout=180.0,
    ) as resp:
        if resp.status_code >= 400:
            body = resp.read().decode("utf-8", errors="replace")
            _fail(f"POST /v1/chat SSE HTTP {resp.status_code}: {body}")
        print("  --- SSE 内容开始 ---")
        raw, events = _consume_sse_stream(resp)
        print("  --- SSE 内容结束 ---")

    result = None
    for name, data in reversed(events):
        if name == "run_result":
            result = data
            break
    return raw, events, result


def resume_sse(
    client: httpx.Client,
    *,
    session_id: str,
    user_reply: str,
    run_id: str,
    await_token: str,
) -> dict[str, Any] | None:
    payload = {
        "session_id": session_id,
        "user_reply": user_reply,
        "run_id": run_id,
        "await_token": await_token,
        "stream": True,
    }
    with client.stream(
        "POST",
        f"{_base()}/v1/chat/resume",
        headers=_headers(session_id),
        json=payload,
        timeout=180.0,
    ) as resp:
        if resp.status_code >= 400:
            body = resp.read().decode("utf-8", errors="replace")
            _fail(f"POST /v1/chat/resume HTTP {resp.status_code}: {body}")
        raw = "".join(resp.iter_text())
    events = parse_sse(raw)
    for name, data in reversed(events):
        if name == "run_result":
            return data
    return None


def test_live_chat_task() -> None:
    """对运行中的 serve 跑一轮真 LLM 对话任务。"""
    base = _base()
    sid = _session_id()
    message = (
        os.environ.get("HUBLOOM_CHAT_MESSAGE") or "状态是available，类别是猫"
    ).strip()
    wait_profile = (os.environ.get("HUBLOOM_WAIT_PROFILE") or "turn_based").strip()

    print("=" * 56)
    print(" Hubloom Serve 真 LLM chat 联调")
    print("=" * 56)
    print(f"URL        : {base}")
    print(f"session_id : {sid}")
    print(f"wait       : {wait_profile}")
    print(f"message    : {message}")
    print(f"token set  : {bool(_token())}")
    print()

    with httpx.Client() as client:
        check_health(client)
        mcp = check_mcp(client)
        if mcp.get("mcp_ready") and not _token():
            print("提示: 未设置 HUBLOOM_MCP_TOKEN（可选；调需鉴权的业务 API 时再带）")

        print(f"\n→ POST /v1/chat（真 LLM）…")
        _raw, events, result = chat_sse(
            client,
            message=message,
            session_id=sid,
            wait_profile=wait_profile,
            stream=True,
        )

        names = [e for e, _ in events]
        print(f"\n收到事件: {names}")

        if result is None:
            _fail("SSE 中未找到 run_result（模型/编排是否异常？）")

        status = result.get("status")
        content = (result.get("content") or "").strip()
        ok = result.get("ok")
        print(f"status     : {status}")
        print(f"ok         : {ok}")
        print(f"journal    : {result.get('journal_run_id')}")
        print(f"content    : {content[:500]}{'…' if len(content) > 500 else ''}")

        assert "run_started" in names
        assert "run_finished" in names
        assert status in {
            "completed",
            "waiting_user",
            "awaiting_user",
            "incomplete",
            "failed",
        }, status
        # 真模型至少要给出可见回复或进入等人状态
        if status in ("completed", "waiting_user", "awaiting_user"):
            assert content, "成功态但 content 为空"
        if status == "failed":
            _fail(f"run_result failed: {result.get('error') or content}")

        # 若 interactive 挂起，可选自动 resume（需环境变量）
        if status == "awaiting_user":
            reply = (os.environ.get("HUBLOOM_RESUME_REPLY") or "").strip()
            awaiting = None
            for name, data in events:
                if name == "awaiting_user":
                    awaiting = data
            if reply and awaiting:
                print(f"\n→ POST /v1/chat/resume「{reply}」…")
                resumed = resume_sse(
                    client,
                    session_id=sid,
                    user_reply=reply,
                    run_id=str(awaiting.get("await_run_id") or ""),
                    await_token=str(awaiting.get("await_token") or ""),
                )
                assert resumed is not None
                print(
                    f"resume status={resumed.get('status')} "
                    f"content={(resumed.get('content') or '')[:300]}"
                )
            else:
                print(
                    "\n提示: 本轮 awaiting_user。"
                    "设置 HUBLOOM_RESUME_REPLY=... 可自动测 /v1/chat/resume"
                )

        hist = client.get(
            f"{_base()}/v1/chat/history",
            params={"session_id": sid},
            headers=_headers(sid),
            timeout=30.0,
        )
        if hist.status_code == 200:
            total = hist.json().get("total", 0)
            print(f"\nok: GET /v1/chat/history total={total}")
            assert total >= 1
        else:
            print(f"warn: history HTTP {hist.status_code}")

    print("\n" + "=" * 56)
    print(" 真 LLM chat 任务通过")
    print("=" * 56)


def main() -> None:
    test_live_chat_task()


if __name__ == "__main__":
    main()
