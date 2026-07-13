"""Travel transport mock API (high-speed rail only)."""

from __future__ import annotations

from fastapi import FastAPI

from .routers import auth, stations, trains, trips, users
from .seed import seed_if_empty

app = FastAPI(
    title="Hubloom Travel Transport API",
    description="差旅演示案例：高铁/动车出行 mock 系统（SQLite 存储）",
    version="0.1.0",
)

app.include_router(auth.router)
app.include_router(stations.router)
app.include_router(trains.router)
app.include_router(trips.router)
app.include_router(users.router)


@app.on_event("startup")
def on_startup() -> None:
    seed_if_empty()


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "service": "travel-transport"}
