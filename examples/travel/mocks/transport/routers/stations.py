"""Station routes."""

from __future__ import annotations

from fastapi import APIRouter, Query

from ..db import connect
from ..schemas import StationOut

router = APIRouter(prefix="/stations", tags=["station"])


@router.get("", response_model=list[StationOut])
def list_stations() -> list[StationOut]:
    with connect() as conn:
        rows = conn.execute("SELECT * FROM stations ORDER BY station_id").fetchall()
    return [
        StationOut(
            station_id=row["station_id"],
            name=row["name"],
            city=row["city"],
            code=row["code"],
        )
        for row in rows
    ]


@router.get("/search", response_model=list[StationOut])
def search_stations(
    city: str | None = Query(default=None),
    q: str | None = Query(default=None),
) -> list[StationOut]:
    sql = "SELECT * FROM stations WHERE 1=1"
    params: list[str] = []
    if city:
        sql += " AND city LIKE ?"
        params.append(f"%{city.strip()}%")
    if q:
        sql += " AND (name LIKE ? OR code LIKE ? OR city LIKE ?)"
        keyword = f"%{q.strip()}%"
        params.extend([keyword, keyword, keyword])
    sql += " ORDER BY station_id"
    with connect() as conn:
        rows = conn.execute(sql, params).fetchall()
    return [
        StationOut(
            station_id=row["station_id"],
            name=row["name"],
            city=row["city"],
            code=row["code"],
        )
        for row in rows
    ]
