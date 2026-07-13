"""Attraction routes."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query, status

from ..db import connect
from ..schemas import AttractionDetail, AttractionSummary, PoliciesOut

router = APIRouter(prefix="/attractions", tags=["attraction"])


def _attraction_summary(row) -> AttractionSummary:
    return AttractionSummary(
        attraction_id=row["attraction_id"],
        name=row["name"],
        city=row["city"],
        address=row["address"],
        phone=row["phone"],
        description=row["description"],
    )


def _get_attraction_or_404(conn, attraction_id: str):
    row = conn.execute(
        "SELECT * FROM attractions WHERE attraction_id = ?",
        (attraction_id,),
    ).fetchone()
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="景区不存在")
    return row


@router.get("", response_model=list[AttractionSummary])
def list_attractions() -> list[AttractionSummary]:
    with connect() as conn:
        rows = conn.execute("SELECT * FROM attractions ORDER BY attraction_id").fetchall()
    return [_attraction_summary(row) for row in rows]


@router.get("/search", response_model=list[AttractionSummary])
def search_attractions(
    city: str | None = Query(default=None),
    q: str | None = Query(default=None),
) -> list[AttractionSummary]:
    sql = "SELECT * FROM attractions WHERE 1=1"
    params: list[str] = []
    if city:
        sql += " AND city LIKE ?"
        params.append(f"%{city.strip()}%")
    if q:
        sql += " AND (name LIKE ? OR address LIKE ? OR description LIKE ?)"
        keyword = f"%{q.strip()}%"
        params.extend([keyword, keyword, keyword])
    sql += " ORDER BY attraction_id"
    with connect() as conn:
        rows = conn.execute(sql, params).fetchall()
    return [_attraction_summary(row) for row in rows]


@router.get("/{attraction_id}", response_model=AttractionDetail)
def get_attraction(attraction_id: str) -> AttractionDetail:
    with connect() as conn:
        row = _get_attraction_or_404(conn, attraction_id)
    summary = _attraction_summary(row)
    return AttractionDetail(
        **summary.model_dump(),
        opening_hours=row["opening_hours"],
        entry_note=row["entry_note"],
    )


@router.get("/{attraction_id}/policies", response_model=PoliciesOut)
def get_attraction_policies(attraction_id: str) -> PoliciesOut:
    with connect() as conn:
        _get_attraction_or_404(conn, attraction_id)
        row = conn.execute(
            "SELECT * FROM attraction_policies WHERE attraction_id = ?",
            (attraction_id,),
        ).fetchone()
        if row is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="政策不存在")
    return PoliciesOut(
        attraction_id=row["attraction_id"],
        entry_policy=row["entry_policy"],
        late_entry_policy=row["late_entry_policy"],
        reschedule_policy=row["reschedule_policy"],
        cancellation_policy=row["cancellation_policy"],
    )
