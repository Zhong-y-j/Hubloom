"""Hotel routes."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query, status

from ..db import connect
from ..schemas import (
    FacilitiesOut,
    HotelDetail,
    HotelSummary,
    PoliciesOut,
    ReviewOut,
)

router = APIRouter(prefix="/hotels", tags=["hotel"])


def _hotel_summary(row) -> HotelSummary:
    return HotelSummary(
        hotel_id=row["hotel_id"],
        name=row["name"],
        city=row["city"],
        address=row["address"],
        phone=row["phone"],
        description=row["description"],
    )


def _hotel_detail(row) -> HotelDetail:
    return HotelDetail(
        hotel_id=row["hotel_id"],
        name=row["name"],
        city=row["city"],
        address=row["address"],
        phone=row["phone"],
        description=row["description"],
        check_in_time=row["check_in_time"],
        check_out_time=row["check_out_time"],
        late_arrival_hold_until=row["late_arrival_hold_until"],
        cancellation_policy=row["cancellation_policy"],
        check_in_note=row["check_in_note"],
    )


def _get_hotel_or_404(conn, hotel_id: str):
    row = conn.execute(
        "SELECT * FROM hotels WHERE hotel_id = ?",
        (hotel_id,),
    ).fetchone()
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="酒店不存在")
    return row


@router.get("", response_model=list[HotelSummary])
def list_hotels() -> list[HotelSummary]:
    with connect() as conn:
        rows = conn.execute("SELECT * FROM hotels ORDER BY hotel_id").fetchall()
    return [_hotel_summary(row) for row in rows]


@router.get("/search", response_model=list[HotelSummary])
def search_hotels(
    city: str | None = Query(default=None, description="城市"),
    q: str | None = Query(default=None, description="关键词"),
) -> list[HotelSummary]:
    sql = "SELECT * FROM hotels WHERE 1=1"
    params: list[str] = []
    if city:
        sql += " AND city LIKE ?"
        params.append(f"%{city.strip()}%")
    if q:
        sql += " AND (name LIKE ? OR address LIKE ? OR description LIKE ?)"
        keyword = f"%{q.strip()}%"
        params.extend([keyword, keyword, keyword])
    sql += " ORDER BY hotel_id"
    with connect() as conn:
        rows = conn.execute(sql, params).fetchall()
    return [_hotel_summary(row) for row in rows]


@router.get("/{hotel_id}", response_model=HotelDetail)
def get_hotel(hotel_id: str) -> HotelDetail:
    with connect() as conn:
        row = _get_hotel_or_404(conn, hotel_id)
    return _hotel_detail(row)


@router.get("/{hotel_id}/facilities", response_model=FacilitiesOut)
def get_hotel_facilities(hotel_id: str) -> FacilitiesOut:
    with connect() as conn:
        _get_hotel_or_404(conn, hotel_id)
        rows = conn.execute(
            "SELECT name FROM hotel_facilities WHERE hotel_id = ? ORDER BY id",
            (hotel_id,),
        ).fetchall()
    return FacilitiesOut(
        hotel_id=hotel_id,
        facilities=[row["name"] for row in rows],
    )


@router.get("/{hotel_id}/policies", response_model=PoliciesOut)
def get_hotel_policies(hotel_id: str) -> PoliciesOut:
    with connect() as conn:
        row = _get_hotel_or_404(conn, hotel_id)
    return PoliciesOut(
        hotel_id=row["hotel_id"],
        check_in_time=row["check_in_time"],
        check_out_time=row["check_out_time"],
        late_arrival_hold_until=row["late_arrival_hold_until"],
        cancellation_policy=row["cancellation_policy"],
        check_in_note=row["check_in_note"],
    )


@router.get("/{hotel_id}/reviews", response_model=list[ReviewOut])
def get_hotel_reviews(hotel_id: str) -> list[ReviewOut]:
    with connect() as conn:
        _get_hotel_or_404(conn, hotel_id)
        rows = conn.execute(
            """
            SELECT author, rating, comment
            FROM hotel_reviews
            WHERE hotel_id = ?
            ORDER BY id
            """,
            (hotel_id,),
        ).fetchall()
    return [
        ReviewOut(author=row["author"], rating=row["rating"], comment=row["comment"])
        for row in rows
    ]
