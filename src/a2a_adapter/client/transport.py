"""出站传输：发现 Card → 流式 SendMessage → 可选过程回调 → 返回最终 answer。"""

from __future__ import annotations

from collections.abc import Callable

import httpx
from a2a.client import A2ACardResolver, ClientConfig, create_client
from a2a.helpers import new_text_message
from a2a.types import Role, SendMessageRequest, TaskState

from a2a_adapter.client.mapping import collect_answer_from_stream
from a2a_adapter.client.registry import RemoteAgent, get_agent
from agents.agent_log import a2a_log, clip

# channel: status | trace | answer ；text 为增量或状态名
OnRemoteEvent = Callable[[str, str], None]


async def discover_card(url: str, *, token: str = ""):
    """拉取远程 Agent Card。"""
    headers = {}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    async with httpx.AsyncClient(timeout=60.0, headers=headers) as http:
        resolver = A2ACardResolver(httpx_client=http, base_url=url.rstrip("/"))
        card = await resolver.get_agent_card()
    a2a_log("client discover", url=url, name=card.name)
    return card


def _artifact_texts(artifact) -> list[str]:
    return [p.text for p in artifact.parts if getattr(p, "text", None)]


def _emit(on_event: OnRemoteEvent | None, channel: str, text: str) -> None:
    if on_event is None or not text:
        return
    try:
        on_event(channel, text)
    except Exception:
        pass


def _print_live_chunk(chunk) -> None:
    """调试用：把远程过程打到终端（不进返回值）。"""
    if chunk.HasField("artifact_update"):
        upd = chunk.artifact_update
        name = (upd.artifact.name or "").strip() or "answer"
        texts = _artifact_texts(upd.artifact)
        if name == "trace":
            for t in texts:
                print(t, end="", flush=True)
            if upd.last_chunk:
                print("\n----- /trace -----\n", flush=True)
        else:
            for t in texts:
                print(t, end="", flush=True)
            if upd.last_chunk:
                print("\n", flush=True)
        return

    if chunk.HasField("status_update"):
        state = chunk.status_update.status.state
        if state == TaskState.TASK_STATE_WORKING:
            print("[WORKING]", flush=True)
        elif state == TaskState.TASK_STATE_COMPLETED:
            print("\n[COMPLETED]", flush=True)
        elif state == TaskState.TASK_STATE_FAILED:
            print("\n[FAILED]", flush=True)
        return

    if chunk.HasField("task"):
        task = chunk.task
        print("[task]", task.status.state, flush=True)
        for art in task.artifacts:
            name = (art.name or "").strip() or "answer"
            print(f"\n----- {name} -----\n", flush=True)
            for t in _artifact_texts(art):
                print(t, end="", flush=True)
            print("\n", flush=True)


def _dispatch_chunk(
    chunk,
    *,
    echo_live: bool,
    on_event: OnRemoteEvent | None,
) -> None:
    if echo_live:
        _print_live_chunk(chunk)

    if chunk.HasField("artifact_update"):
        upd = chunk.artifact_update
        name = (upd.artifact.name or "").strip() or "answer"
        texts = _artifact_texts(upd.artifact)
        channel = "trace" if name == "trace" else "answer"
        for t in texts:
            _emit(on_event, channel, t)
        return

    if chunk.HasField("status_update"):
        state = chunk.status_update.status.state
        if state == TaskState.TASK_STATE_WORKING:
            _emit(on_event, "status", "working")
        elif state == TaskState.TASK_STATE_COMPLETED:
            _emit(on_event, "status", "completed")
        elif state == TaskState.TASK_STATE_FAILED:
            _emit(on_event, "status", "failed")
        return

    if chunk.HasField("task"):
        task = chunk.task
        for art in task.artifacts:
            name = (art.name or "").strip() or "answer"
            channel = "trace" if name == "trace" else "answer"
            for t in _artifact_texts(art):
                _emit(on_event, channel, t)


async def send_and_wait_answer(
    agent: RemoteAgent,
    message: str,
    *,
    timeout: float = 180.0,
    echo_live: bool = True,
    on_event: OnRemoteEvent | None = None,
) -> str:
    """向远程发消息：流式收包；过程经 on_event / echo_live；返回最终 answer。"""
    text = (message or "").strip()
    if not text:
        raise ValueError("message 不能为空")
    a2a_log(
        "client send",
        agent_id=agent.id,
        url=agent.url,
        message=clip(text, 80),
        has_token=bool(agent.token),
    )
    headers = {}
    if agent.token:
        headers["Authorization"] = f"Bearer {agent.token}"
    async with httpx.AsyncClient(timeout=timeout, headers=headers) as http:
        resolver = A2ACardResolver(httpx_client=http, base_url=agent.url)
        card = await resolver.get_agent_card()
        if not card.capabilities.streaming:
            card.capabilities.streaming = True
            a2a_log("client force streaming on card", agent_id=agent.id)
        client = await create_client(
            agent=card,
            client_config=ClientConfig(streaming=True),
        )
        try:
            request = SendMessageRequest(
                message=new_text_message(text, role=Role.ROLE_USER),
            )
            chunks = []
            if echo_live:
                print("\n----- remote stream -----\n", flush=True)
            _emit(on_event, "status", "working")
            async for chunk in client.send_message(request):
                _dispatch_chunk(chunk, echo_live=echo_live, on_event=on_event)
                chunks.append(chunk)
            answer = collect_answer_from_stream(chunks)
            _emit(on_event, "status", "completed")
        finally:
            await client.close()
    a2a_log(
        "client completed",
        agent_id=agent.id,
        answer_len=len(answer),
        answer=clip(answer, 80),
    )
    return answer


async def delegate(
    agent_id: str,
    message: str,
    *,
    echo_live: bool = True,
    on_event: OnRemoteEvent | None = None,
) -> str:
    """目录里按 id 查找再委托。"""
    agent = get_agent(agent_id)
    if agent is None:
        raise KeyError(f"unknown agent_id: {agent_id!r}（检查 a2a.remote_agents）")
    return await send_and_wait_answer(
        agent,
        message,
        echo_live=echo_live,
        on_event=on_event,
    )


if __name__ == "__main__":
    import asyncio
    import os

    async def _demo() -> None:
        agent_id = os.getenv("A2A_DEMO_AGENT_ID", "hubloom-self")
        msg = os.getenv("A2A_DEMO_MESSAGE", "你好，帮我查询一下当前有哪些小区。")
        print("delegate →", agent_id, repr(msg))
        answer = await delegate(agent_id, msg, echo_live=True)
        print("\n===== final answer (return value) =====\n")
        print(answer)

    asyncio.run(_demo())
