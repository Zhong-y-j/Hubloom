"""Business helpers for the attraction mock."""

from __future__ import annotations

from datetime import datetime
from uuid import uuid4

SERVICE_FEE = 5.0


def now_iso() -> str:
    return datetime.now().replace(microsecond=0).isoformat()


def new_ticket_id() -> str:
    return f"TKT-{uuid4().hex[:8].upper()}"


def row_to_ticket(row) -> dict:
    return {
        "ticket_id": row["ticket_id"],
        "attraction_id": row["attraction_id"],
        "attraction_name": row["attraction_name"],
        "ticket_type_id": row["ticket_type_id"],
        "ticket_type_name": row["ticket_type_name"],
        "trip_id": row["trip_id"],
        "visitor_name": row["visitor_name"],
        "visitor_phone": row["visitor_phone"],
        "visit_date": row["visit_date"],
        "entry_slot": row["entry_slot"],
        "status": row["status"],
        "total_price": row["total_price"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }
