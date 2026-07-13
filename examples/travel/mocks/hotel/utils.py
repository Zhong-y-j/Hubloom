"""Business helpers for the hotel mock."""

from __future__ import annotations

from datetime import date, datetime, timedelta
from uuid import uuid4

TAX_RATE = 0.06


def parse_date(value: str) -> date:
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise ValueError(f"无效日期: {value}") from exc


def nights_between(check_in: str, check_out: str) -> int:
    start = parse_date(check_in)
    end = parse_date(check_out)
    delta = (end - start).days
    if delta <= 0:
        raise ValueError("退房日期必须晚于入住日期")
    return delta


def stay_dates(check_in: str, check_out: str) -> list[str]:
    start = parse_date(check_in)
    end = parse_date(check_out)
    days: list[str] = []
    current = start
    while current < end:
        days.append(current.isoformat())
        current += timedelta(days=1)
    return days


def now_iso() -> str:
    return datetime.now().replace(microsecond=0).isoformat()


def new_booking_id() -> str:
    return f"HTL-{uuid4().hex[:8].upper()}"


def calc_price(room_subtotal: float, tax_rate: float = TAX_RATE) -> tuple[float, float]:
    tax_amount = round(room_subtotal * tax_rate, 2)
    total = round(room_subtotal + tax_amount, 2)
    return tax_amount, total


def row_to_booking(row, hotel_name: str, room_type_name: str) -> dict:
    return {
        "booking_id": row["booking_id"],
        "hotel_id": row["hotel_id"],
        "hotel_name": hotel_name,
        "room_type_id": row["room_type_id"],
        "room_type_name": room_type_name,
        "trip_id": row["trip_id"],
        "guest_name": row["guest_name"],
        "guest_phone": row["guest_phone"],
        "check_in": row["check_in"],
        "check_out": row["check_out"],
        "status": row["status"],
        "total_price": row["total_price"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }
