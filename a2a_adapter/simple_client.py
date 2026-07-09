"""最简 A2A Client：三步走 —— 发现 → 建连 → 发消息。

运行前先起 Server：
  uv run python -m a2a_adapter.simple_server

再测 Client：
  uv run python -m a2a_adapter.simple_client
"""

from __future__ import annotations

import asyncio

import httpx
from a2a.client import A2ACardResolver, ClientConfig, create_client
from a2a.helpers import new_text_message
from a2a.types import Role, SendMessageRequest

# 远程 Agent 的根地址（不是具体 API 路径）
AGENT_BASE_URL = "http://127.0.0.1:9000"


async def main() -> None:
    async with httpx.AsyncClient() as http:

        # ① 发现：拉取 Agent Card（通常是 /.well-known/agent-card.json）
        resolver = A2ACardResolver(httpx_client=http, base_url=AGENT_BASE_URL)
        card = await resolver.get_agent_card()
        print(f"发现 Agent: {card.name}")
        print(f"描述: {card.description}")

        # ② 建连：用 Card 里的端点信息创建 Client
        client = await create_client(
            agent=card,
            client_config=ClientConfig(streaming=False),
        )

        try:
            # ③ 发消息：构造一条文本 Message，发给远程 Agent
            message = new_text_message("Say hello.", role=Role.ROLE_USER)
            request = SendMessageRequest(message=message)

            print("\n发送中…")
            async for chunk in client.send_message(request):
                # 非流式时通常只有一个最终 Task / Message
                print(chunk)
        finally:
            await client.close()


if __name__ == "__main__":
    asyncio.run(main())
