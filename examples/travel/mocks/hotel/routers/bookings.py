"""Booking routes."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, status

from ..db import connect
from ..deps import get_current_user
from ..schemas import (
    BookingCreateRequest,
    BookingOut,
    CancelOut,
    GuestInfoUpdateRequest,
    PriceBreakdownOut,
    QuoteOut,
    QuoteRequest,
)
from ..utils import (
    TAX_RATE,
    calc_price,
    new_booking_id,
    nights_between,
    now_iso,
    row_to_booking,
    stay_dates,
)

router = APIRouter(prefix="/bookings", tags=["booking"])


def _load_booking(conn, booking_id: str):
    row = conn.execute(
        """
        SELECT b.*, h.name AS hotel_name, r.name AS room_type_name
        FROM bookings b
        JOIN hotels h ON h.hotel_id = b.hotel_id
        JOIN room_types r ON r.room_type_id = b.room_type_id
        WHERE b.booking_id = ?
        """,
        (booking_id,),
    ).fetchone()
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="订单不存在")
    return row


def _ensure_owned(row, user: dict) -> None:
    if row["user_id"] != user["user_id"]:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="无权访问该订单")


def _quote_from_db(conn, *, hotel_id: str, room_type_id: str, check_in: str, check_out: str) -> QuoteOut:
    hotel = conn.execute(
        "SELECT hotel_id FROM hotels WHERE hotel_id = ?",
        (hotel_id,),
    ).fetchone()
    if hotel is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="酒店不存在")

    room = conn.execute(
        "SELECT * FROM room_types WHERE room_type_id = ?",
        (room_type_id,),
    ).fetchone()
    if room is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="房型不存在")
    if room["hotel_id"] != hotel_id:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="房型不属于该酒店")

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
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="所选日期不可订")
    if any(row["available_count"] <= 0 for row in rows):
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="房间库存不足")

    room_subtotal = round(sum(row["price"] for row in rows), 2)
    tax_amount, total_price = calc_price(room_subtotal, TAX_RATE)
    return QuoteOut(
        hotel_id=hotel_id,
        room_type_id=room_type_id,
        check_in=check_in,
        check_out=check_out,
        nights=nights,
        room_subtotal=room_subtotal,
        tax_rate=TAX_RATE,
        tax_amount=tax_amount,
        total_price=total_price,
    )


@router.post("/quote", response_model=QuoteOut)
def quote_booking(body: QuoteRequest) -> QuoteOut:
    try:
        with connect() as conn:
            return _quote_from_db(
                conn,
                hotel_id=body.hotel_id,
                room_type_id=body.room_type_id,
                check_in=body.check_in,
                check_out=body.check_out,
            )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


@router.post("", response_model=BookingOut, status_code=status.HTTP_201_CREATED)
def create_booking(
    body: BookingCreateRequest,
    user: dict = Depends(get_current_user),
) -> BookingOut:
    try:
        with connect() as conn:
            quote = _quote_from_db(
                conn,
                hotel_id=body.hotel_id,
                room_type_id=body.room_type_id,
                check_in=body.check_in,
                check_out=body.check_out,
            )
            booking_id = new_booking_id()
            timestamp = now_iso()
            conn.execute(
                """
                INSERT INTO bookings (
                    booking_id, user_id, hotel_id, room_type_id, trip_id,
                    guest_name, guest_phone, check_in, check_out, status,
                    room_rate, tax_rate, total_price, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    booking_id,
                    user["user_id"],
                    body.hotel_id,
                    body.room_type_id,
                    body.trip_id,
                    body.guest_name,
                    body.guest_phone,
                    body.check_in,
                    body.check_out,
                    "confirmed",
                    quote.room_subtotal,
                    quote.tax_rate,
                    quote.total_price,
                    timestamp,
                    timestamp,
                ),
            )
            for stay_day in stay_dates(body.check_in, body.check_out):
                conn.execute(
                    """
                    UPDATE inventory
                    SET available_count = available_count - 1
                    WHERE hotel_id = ? AND room_type_id = ? AND stay_date = ?
                    """,
                    (body.hotel_id, body.room_type_id, stay_day),
                )
            conn.execute(
                """
                INSERT INTO booking_events (booking_id, status, note, created_at)
                VALUES (?, ?, ?, ?)
                """,
                (booking_id, "confirmed", "预订已创建", timestamp),
            )
            conn.commit()
            row = _load_booking(conn, booking_id)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

    return BookingOut(**row_to_booking(row, row["hotel_name"], row["room_type_name"]))


@router.get("", response_model=list[BookingOut])
def list_bookings(
    status_filter: str | None = Query(default=None, alias="status"),
    from_date: str | None = Query(default=None, description="入住日起 YYYY-MM-DD"),
    user: dict = Depends(get_current_user),
) -> list[BookingOut]:
    sql = """
        SELECT b.*, h.name AS hotel_name, r.name AS room_type_name
        FROM bookings b
        JOIN hotels h ON h.hotel_id = b.hotel_id
        JOIN room_types r ON r.room_type_id = b.room_type_id
        WHERE b.user_id = ?
    """
    params: list[str] = [user["user_id"]]
    if status_filter:
        sql += " AND b.status = ?"
        params.append(status_filter)
    if from_date:
        sql += " AND b.check_in >= ?"
        params.append(from_date)
    sql += " ORDER BY b.created_at DESC"

    with connect() as conn:
        rows = conn.execute(sql, params).fetchall()
    return [
        BookingOut(**row_to_booking(row, row["hotel_name"], row["room_type_name"]))
        for row in rows
    ]


@router.get("/by-trip/{trip_id}", response_model=list[BookingOut])
def list_bookings_by_trip(
    trip_id: str,
    user: dict = Depends(get_current_user),
) -> list[BookingOut]:
    with connect() as conn:
        rows = conn.execute(
            """
            SELECT b.*, h.name AS hotel_name, r.name AS room_type_name
            FROM bookings b
            JOIN hotels h ON h.hotel_id = b.hotel_id
            JOIN room_types r ON r.room_type_id = b.room_type_id
            WHERE b.user_id = ? AND b.trip_id = ?
            ORDER BY b.created_at DESC
            """,
            (user["user_id"], trip_id),
        ).fetchall()
    return [
        BookingOut(**row_to_booking(row, row["hotel_name"], row["room_type_name"]))
        for row in rows
    ]


@router.get("/{booking_id}", response_model=BookingOut)
def get_booking(
    booking_id: str,
    user: dict = Depends(get_current_user),
) -> BookingOut:
    with connect() as conn:
        row = _load_booking(conn, booking_id)
        _ensure_owned(row, user)
    return BookingOut(**row_to_booking(row, row["hotel_name"], row["room_type_name"]))


@router.get("/{booking_id}/price-breakdown", response_model=PriceBreakdownOut)
def get_price_breakdown(
    booking_id: str,
    user: dict = Depends(get_current_user),
) -> PriceBreakdownOut:
    with connect() as conn:
        row = _load_booking(conn, booking_id)
        _ensure_owned(row, user)
    nights = nights_between(row["check_in"], row["check_out"])
    room_subtotal = row["room_rate"]
    tax_amount, total_price = calc_price(room_subtotal, row["tax_rate"])
    return PriceBreakdownOut(
        booking_id=row["booking_id"],
        nights=nights,
        room_rate=row["room_rate"],
        room_subtotal=room_subtotal,
        tax_rate=row["tax_rate"],
        tax_amount=tax_amount,
        total_price=total_price,
    )


@router.patch("/{booking_id}/guest-info", response_model=BookingOut)
def update_guest_info(
    booking_id: str,
    body: GuestInfoUpdateRequest,
    user: dict = Depends(get_current_user),
) -> BookingOut:
    if body.guest_name is None and body.guest_phone is None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="至少提供一个字段")

    with connect() as conn:
        row = _load_booking(conn, booking_id)
        _ensure_owned(row, user)
        if row["status"] == "cancelled":
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="订单已取消")

        guest_name = body.guest_name or row["guest_name"]
        guest_phone = body.guest_phone or row["guest_phone"]
        updated_at = now_iso()
        conn.execute(
            """
            UPDATE bookings
            SET guest_name = ?, guest_phone = ?, updated_at = ?
            WHERE booking_id = ?
            """,
            (guest_name, guest_phone, updated_at, booking_id),
        )
        conn.execute(
            """
            INSERT INTO booking_events (booking_id, status, note, created_at)
            VALUES (?, ?, ?, ?)
            """,
            (booking_id, row["status"], "更新入住人信息", updated_at),
        )
        conn.commit()
        row = _load_booking(conn, booking_id)

    return BookingOut(**row_to_booking(row, row["hotel_name"], row["room_type_name"]))


@router.post("/{booking_id}/cancel", response_model=CancelOut)
def cancel_booking(
    booking_id: str,
    user: dict = Depends(get_current_user),
) -> CancelOut:
    with connect() as conn:
        row = _load_booking(conn, booking_id)
        _ensure_owned(row, user)
        if row["status"] == "cancelled":
            return CancelOut(
                booking_id=booking_id,
                status="cancelled",
                message="订单已是取消状态",
            )

        updated_at = now_iso()
        conn.execute(
            """
            UPDATE bookings
            SET status = 'cancelled', updated_at = ?
            WHERE booking_id = ?
            """,
            (updated_at, booking_id),
        )
        for stay_day in stay_dates(row["check_in"], row["check_out"]):
            conn.execute(
                """
                UPDATE inventory
                SET available_count = available_count + 1
                WHERE hotel_id = ? AND room_type_id = ? AND stay_date = ?
                """,
                (row["hotel_id"], row["room_type_id"], stay_day),
            )
        conn.execute(
            """
            INSERT INTO booking_events (booking_id, status, note, created_at)
            VALUES (?, ?, ?, ?)
            """,
            (booking_id, "cancelled", "订单已取消", updated_at),
        )
        conn.commit()

    return CancelOut(
        booking_id=booking_id,
        status="cancelled",
        message="订单取消成功，库存已恢复",
    )
