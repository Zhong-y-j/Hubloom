"""把 Card + Executor 组装成 A2A 路由（可独立跑，也可挂进主 FastAPI）。

- 造名片：agents/a2a/card.py
- 状态机：executor.py（内部用 mapping）
- 这里只接线：Card 路由 + JSON-RPC → HubloomExecutor
"""

from __future__ import annotations

from a2a.server.request_handlers import DefaultRequestHandler
from a2a.server.routes import create_agent_card_routes, create_jsonrpc_routes
from a2a.server.tasks import InMemoryTaskStore
from a2a.types import AgentCard
from starlette.applications import Starlette
from starlette.routing import Route

from a2a_adapter.server.executor import HubloomExecutor, RunTurn

# 独立调试进程默认端口（主服务挂载后请用 CORTEX_API_PORT，一般 8000）
HOST = "127.0.0.1"
PORT = 9000
BASE_URL = f"http://{HOST}:{PORT}"


def build_a2a_routes(
    card: AgentCard,
    run_turn: RunTurn | None = None,
    *,
    rpc_url: str = "/",
) -> list[Route]:
    """Card 发现 + JSON-RPC 路由列表（供 FastAPI / Starlette 挂载）。"""
    handler = DefaultRequestHandler(
        agent_executor=HubloomExecutor(run_turn=run_turn),
        task_store=InMemoryTaskStore(),
        agent_card=card,
    )
    return [
        *create_agent_card_routes(card),
        *create_jsonrpc_routes(handler, rpc_url),
    ]


def build_app(
    card: AgentCard,
    run_turn: RunTurn | None = None,
    *,
    rpc_url: str = "/",
) -> Starlette:
    """独立 Starlette 应用（学习 / 单独起进程用）。"""
    return Starlette(routes=build_a2a_routes(card, run_turn, rpc_url=rpc_url))


if __name__ == "__main__":
    import asyncio

    import uvicorn

    from agents.a2a.bridge import run_a2a_turn
    from agents.a2a.card import build_agent_card
    from agents.app.bootstrap import build_runtime_async
    from mcp_adapter.gateway.catalog import load_catalog

    async def _make_app() -> Starlette:
        catalog = await load_catalog()
        card = await build_agent_card(BASE_URL, catalog)
        runtime = await build_runtime_async()

        async def run_turn(query: str, task_id: str, on_stream) -> str:
            return await run_a2a_turn(
                runtime,
                query,
                task_id=task_id,
                on_stream=on_stream,
            )

        return build_app(card, run_turn=run_turn)

    app = asyncio.run(_make_app())
    print(f"A2A Server listening on {BASE_URL}")
    print(f"Agent Card: {BASE_URL}/.well-known/agent-card.json")
    uvicorn.run(app, host=HOST, port=PORT)
