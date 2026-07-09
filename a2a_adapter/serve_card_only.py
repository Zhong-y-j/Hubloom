"""临时：只挂 Agent Card，方便调试发现接口。"""

from __future__ import annotations

import asyncio

import uvicorn
from a2a.server.routes import create_agent_card_routes
from starlette.applications import Starlette

from agents.a2a.card import build_agent_card
from mcp_adapter.gateway.catalog import load_catalog

HOST = "127.0.0.1"
PORT = 9999
PUBLIC_URL = f"http://{HOST}:{PORT}"


async def _build_app() -> Starlette:
    catalog = await load_catalog()
    print("catalog tags:", catalog.list_tags())
    card = await build_agent_card(PUBLIC_URL, catalog)

    print("card description:", card.description)
    for s in card.skills:
        print(f"  - {s.id}: {s.description} | {list(s.examples)}")
    routes = create_agent_card_routes(card)
    return Starlette(routes=routes)


def main() -> None:
    app = asyncio.run(_build_app())
    print(f"Agent Card: {PUBLIC_URL}/.well-known/agent-card.json")
    uvicorn.run(app, host=HOST, port=PORT)


if __name__ == "__main__":
    main()
