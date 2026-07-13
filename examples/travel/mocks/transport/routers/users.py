"""User routes."""

from __future__ import annotations

from fastapi import APIRouter, Depends

from ..db import connect
from ..deps import get_current_user
from ..schemas import TripOut, TripSummaryOut, UserOut
from ..utils import row_to_trip

router = APIRouter(prefix="/users", tags=["user"])


@router.get("/me", response_model=UserOut)
def get_me(user: dict = Depends(get_current_user)) -> UserOut:
    return UserOut(
        user_id=user["user_id"],
        username=user["username"],
        display_name=user["display_name"],
        phone=user["phone"],
        email=user["email"],
    )


@router.get("/me/trip-summary", response_model=TripSummaryOut)
def get_trip_summary(user: dict = Depends(get_current_user)) -> TripSummaryOut:
    with connect() as conn:
        rows = conn.execute(
            """
            SELECT t.*, tr.train_type,
                   st.name AS seat_type_name,
                   fs.name AS from_station_name,
                   ts.name AS to_station_name
            FROM trips t
            JOIN trains tr ON tr.train_no = t.train_no
            JOIN seat_types st ON st.seat_type_id = t.seat_type_id
            JOIN stations fs ON fs.station_id = t.from_station_id
            JOIN stations ts ON ts.station_id = t.to_station_id
            WHERE t.user_id = ?
            ORDER BY t.created_at DESC
            """,
            (user["user_id"],),
        ).fetchall()

    total = len(rows)
    confirmed = sum(1 for row in rows if row["status"] == "confirmed")
    delayed = sum(1 for row in rows if row["status"] == "delayed")
    cancelled = sum(1 for row in rows if row["status"] == "cancelled")
    latest = None
    if rows:
        latest = TripOut(**row_to_trip(rows[0]))

    return TripSummaryOut(
        total=total,
        confirmed=confirmed,
        delayed=delayed,
        cancelled=cancelled,
        latest_trip=latest,
    )
