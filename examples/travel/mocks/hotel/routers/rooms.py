"""Room and availability routes."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query, status

from ..db import connect
from ..schemas import AvailabilityItem, AvailabilityOut, RoomTypeDetail, RoomTypeSummary
from ..utils import TAX_RATE, calc_price, nights_between, stay_dates

router = APIRouter(tags=["room"])


def _room_summary(row) -> RoomTypeSummary:
    return RoomTypeSummary(
        room_type_id=row["room_type_id"],
        hotel_id=row["hotel_id"],
        name=row["name"],
        bed_type=row["bed_type"],
        area_sqm=row["area_sqm"],
        max_guests=row["max_guests"],
        base_price=row["base_price"],
    )


def _room_detail(row) -> RoomTypeDetail:
    return RoomTypeDetail(
        room_type_id=row["room_type_id"],
        hotel_id=row["hotel_id"],
        name=row["name"],
        bed_type=row["bed_type"],
        area_sqm=row["area_sqm"],
        max_guests=row["max_guests"],
        base_price=row["base_price"],
        description=row["description"],
    )


def _get_room_type_or_404(conn, room_type_id: str):
    row = conn.execute(
        "SELECT * FROM room_types WHERE room_type_id = ?",
        (room_type_id,),
    ).fetchone()
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="房型不存在")
    return row


def _availability_for_room(
    conn,
    *,
    hotel_id: str,
    room_type_id: str,
    room_type_name: str,
    check_in: str,
    check_out: str,
) -> AvailabilityItem:
    nights = nights_between(check_in, check_out)
    dates = stay_dates(check_in, check_out)
    placeholders = ",".join("?" for _ in dates)
    rows = conn.execute(
        f"""
        SELECT stay_date, available_count, price
        FROM inventory
        WHERE hotel_id = ? AND room_type_id = ? AND stay_date IN ({placeholders})
        ORDER BY stay_date
        """,
        [hotel_id, room_type_id, *dates],
    ).fetchall()
    if len(rows) != len(dates):
        return AvailabilityItem(
            room_type_id=room_type_id,
            room_type_name=room_type_name,
            available=False,
            available_count=0,
            nightly_price=0.0,
            total_nights=nights,
            total_price=0.0,
        )
    min_available = min(row["available_count"] for row in rows)
    nightly_price = max(row["price"] for row in rows)
    total_price = round(sum(row["price"] for row in rows), 2)
    return AvailabilityItem(
        room_type_id=room_type_id,
        room_type_name=room_type_name,
        available=min_available > 0,
        available_count=min_available,
        nightly_price=nightly_price,
        total_nights=nights,
        total_price=total_price,
    )


@router.get("/hotels/{hotel_id}/room-types", response_model=list[RoomTypeSummary])
def list_room_types(hotel_id: str) -> list[RoomTypeSummary]:
    with connect() as conn:
        hotel = conn.execute(
            "SELECT hotel_id FROM hotels WHERE hotel_id = ?",
            (hotel_id,),
        ).fetchone()
        if hotel is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="酒店不存在")
        rows = conn.execute(
            "SELECT * FROM room_types WHERE hotel_id = ? ORDER BY room_type_id",
            (hotel_id,),
        ).fetchall()
    return [_room_summary(row) for row in rows]


@router.get("/room-types/{room_type_id}", response_model=RoomTypeDetail)
def get_room_type(room_type_id: str) -> RoomTypeDetail:
    with connect() as conn:
        row = _get_room_type_or_404(conn, room_type_id)
    return _room_detail(row)


@router.get("/hotels/{hotel_id}/availability", response_model=AvailabilityOut)
def get_availability(
    hotel_id: str,
    check_in: str = Query(..., description="入住日期 YYYY-MM-DD"),
    check_out: str = Query(..., description="退房日期 YYYY-MM-DD"),
    room_type_id: str | None = Query(default=None, description="可选房型 ID"),
) -> AvailabilityOut:
    try:
        nights_between(check_in, check_out)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

    with connect() as conn:
        hotel = conn.execute(
            "SELECT hotel_id FROM hotels WHERE hotel_id = ?",
            (hotel_id,),
        ).fetchone()
        if hotel is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="酒店不存在")

        if room_type_id:
            row = _get_room_type_or_404(conn, room_type_id)
            if row["hotel_id"] != hotel_id:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="房型不属于该酒店",
                )
            room_rows = [row]
        else:
            room_rows = conn.execute(
                "SELECT * FROM room_types WHERE hotel_id = ? ORDER BY room_type_id",
                (hotel_id,),
            ).fetchall()

        items = [
            _availability_for_room(
                conn,
                hotel_id=hotel_id,
                room_type_id=row["room_type_id"],
                room_type_name=row["name"],
                check_in=check_in,
                check_out=check_out,
            )
            for row in room_rows
        ]

    return AvailabilityOut(
        hotel_id=hotel_id,
        check_in=check_in,
        check_out=check_out,
        items=items,
    )
