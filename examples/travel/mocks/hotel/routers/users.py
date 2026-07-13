"""User routes."""

from __future__ import annotations

from fastapi import APIRouter, Depends

from ..db import connect
from ..deps import get_current_user
from ..schemas import BookingOut, BookingSummaryOut, UserOut
from ..utils import row_to_booking

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


@router.get("/me/booking-summary", response_model=BookingSummaryOut)
def get_booking_summary(user: dict = Depends(get_current_user)) -> BookingSummaryOut:
    with connect() as conn:
        rows = conn.execute(
            """
            SELECT b.*, h.name AS hotel_name, r.name AS room_type_name
            FROM bookings b
            JOIN hotels h ON h.hotel_id = b.hotel_id
            JOIN room_types r ON r.room_type_id = b.room_type_id
            WHERE b.user_id = ?
            ORDER BY b.created_at DESC
            """,
            (user["user_id"],),
        ).fetchall()

    total = len(rows)
    confirmed = sum(1 for row in rows if row["status"] == "confirmed")
    cancelled = sum(1 for row in rows if row["status"] == "cancelled")
    latest = None
    if rows:
        row = rows[0]
        latest = BookingOut(**row_to_booking(row, row["hotel_name"], row["room_type_name"]))

    return BookingSummaryOut(
        total=total,
        confirmed=confirmed,
        cancelled=cancelled,
        latest_booking=latest,
    )
