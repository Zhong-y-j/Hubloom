"""Travel attraction mock API."""

from __future__ import annotations

import asyncio
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from starlette.staticfiles import StaticFiles

from .bridge.hubloom import router as hubloom_bridge_router
from .routers import attractions, auth, ticket_types, tickets, users
from .seed import seed_if_empty

_STATIC_DIR = Path(__file__).resolve().parent / "static"
_NO_CACHE = "no-cache, no-store, must-revalidate"


def _html_response(filename: str) -> FileResponse:
    path = _STATIC_DIR / filename
    if not path.is_file():
        raise HTTPException(status_code=404, detail=f"页面未找到: {filename}")
    return FileResponse(
        path,
        headers={"Cache-Control": _NO_CACHE, "Pragma": "no-cache"},
    )


app = FastAPI(
    title="Hubloom Travel Attraction API",
    description="差旅演示案例：景区门票预约 mock 系统（SQLite 存储）",
    version="0.1.0",
)

app.include_router(auth.router)
app.include_router(attractions.router)
app.include_router(ticket_types.router)
app.include_router(tickets.router)
app.include_router(users.router)
app.include_router(hubloom_bridge_router)

if _STATIC_DIR.is_dir():
    app.mount("/static", StaticFiles(directory=_STATIC_DIR), name="static")


@app.on_event("startup")
async def on_startup() -> None:
    seed_if_empty()
    from .bridge.prime import prime_hubloom_retry

    asyncio.create_task(prime_hubloom_retry())


@app.get("/")
async def root_login_page() -> FileResponse:
    return _html_response("login.html")


@app.get("/login")
async def login_page() -> FileResponse:
    return _html_response("login.html")


@app.get("/chat")
async def chat_page() -> FileResponse:
    return _html_response("chat.html")


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "service": "travel-attraction"}
