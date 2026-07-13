"""User routes."""

from __future__ import annotations

from fastapi import APIRouter, Depends

from ..db import connect
from ..deps import get_current_user
from ..schemas import TicketOut, TicketSummaryOut, UserOut
from ..utils import row_to_ticket

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


@router.get("/me/ticket-summary", response_model=TicketSummaryOut)
def get_ticket_summary(user: dict = Depends(get_current_user)) -> TicketSummaryOut:
    with connect() as conn:
        rows = conn.execute(
            """
            SELECT t.*, a.name AS attraction_name, tt.name AS ticket_type_name
            FROM tickets t
            JOIN attractions a ON a.attraction_id = t.attraction_id
            JOIN ticket_types tt ON tt.ticket_type_id = t.ticket_type_id
            WHERE t.user_id = ?
            ORDER BY t.created_at DESC
            """,
            (user["user_id"],),
        ).fetchall()

    total = len(rows)
    confirmed = sum(1 for row in rows if row["status"] == "confirmed")
    cancelled = sum(1 for row in rows if row["status"] == "cancelled")
    latest = None
    if rows:
        latest = TicketOut(**row_to_ticket(rows[0]))

    return TicketSummaryOut(
        total=total,
        confirmed=confirmed,
        cancelled=cancelled,
        latest_ticket=latest,
    )
