"""Travel attraction mock API."""

from __future__ import annotations

from fastapi import FastAPI

from .routers import attractions, auth, ticket_types, tickets, users
from .seed import seed_if_empty

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


@app.on_event("startup")
def on_startup() -> None:
    seed_if_empty()


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "service": "travel-attraction"}
