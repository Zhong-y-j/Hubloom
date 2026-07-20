"""最简 A2A Client：流式打印 answer + trace（思考/工具）。"""

from __future__ import annotations

import asyncio
import sys

import httpx
from a2a.client import A2ACardResolver, ClientConfig, create_client
from a2a.helpers import new_text_message
from a2a.types import Role, SendMessageRequest, TaskState

import os

# 与主 FastAPI 同地址；可用 CORTEX_PUBLIC_URL 覆盖
AGENT_BASE_URL = (
    os.getenv("CORTEX_PUBLIC_URL")
    or f"http://127.0.0.1:{os.getenv('CORTEX_API_PORT', '8001')}"
).rstrip("/")


def _print_artifact_chunk(chunk) -> None:
    if not chunk.HasField("artifact_update"):
        return
    update = chunk.artifact_update
    name = update.artifact.name or "answer"
    texts = [p.text for p in update.artifact.parts if p.text]
    if not texts and not update.last_chunk:
        return

    if name == "trace":
        for text in texts:
            print(text, end="", flush=True)
        if update.last_chunk:
            print("\n----- /trace -----\n", flush=True)
        return

    # 主回答
    for text in texts:
        print(text, end="", flush=True)
    if update.last_chunk:
        print("\n", flush=True)


async def main() -> None:
    async with httpx.AsyncClient(timeout=120.0) as http:
        resolver = A2ACardResolver(httpx_client=http, base_url=AGENT_BASE_URL)
        card = await resolver.get_agent_card()
        print(f"发现 Agent: {card.name}")
        print(f"描述: {card.description}")

        client = await create_client(
            agent=card,
            client_config=ClientConfig(streaming=True),
        )

        try:
            # 想看 Thought+工具时，改成会触发查 API 的句子，例如：
            # 「帮我查一下 id 为 1 的宠物信息」
            message = new_text_message(
                "帮我查一下当前有哪些小区",
                role=Role.ROLE_USER,
            )
            request = SendMessageRequest(message=message)

            print("\n发送中（流式）…\n")
            print("----- trace -----", flush=True)
            async for chunk in client.send_message(request):
                _print_artifact_chunk(chunk)

                if chunk.HasField("status_update"):
                    state = chunk.status_update.status.state
                    if state == TaskState.TASK_STATE_COMPLETED:
                        print("[COMPLETED]")
                    elif state == TaskState.TASK_STATE_FAILED:
                        msg = chunk.status_update.status.message
                        detail = ""
                        if msg.parts:
                            detail = msg.parts[0].text
                        print(f"[FAILED] {detail}", file=sys.stderr)
        finally:
            await client.close()


if __name__ == "__main__":
    asyncio.run(main())
