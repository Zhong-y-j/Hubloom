"""Business helpers for the transport mock."""

from __future__ import annotations

from datetime import datetime
from uuid import uuid4

SERVICE_FEE = 15.0


def now_iso() -> str:
    return datetime.now().replace(microsecond=0).isoformat()


def new_trip_id() -> str:
    return f"TRIP-{uuid4().hex[:8].upper()}"


def row_to_trip(row) -> dict:
    return {
        "trip_id": row["trip_id"],
        "train_no": row["train_no"],
        "train_type": row["train_type"],
        "travel_date": row["travel_date"],
        "seat_type_id": row["seat_type_id"],
        "seat_type_name": row["seat_type_name"],
        "passenger_name": row["passenger_name"],
        "passenger_phone": row["passenger_phone"],
        "from_station_id": row["from_station_id"],
        "from_station_name": row["from_station_name"],
        "to_station_id": row["to_station_id"],
        "to_station_name": row["to_station_name"],
        "status": row["status"],
        "total_price": row["total_price"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }
