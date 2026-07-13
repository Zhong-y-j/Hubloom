"""Trip routes."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, status

from ..db import connect
from ..deps import get_current_user
from ..schemas import (
    CancelOut,
    PassengerInfoUpdateRequest,
    PriceBreakdownOut,
    QuoteOut,
    QuoteRequest,
    TripCreateRequest,
    TripEventOut,
    TripOut,
    TripTimelineOut,
)
from ..utils import SERVICE_FEE, new_trip_id, now_iso, row_to_trip

router = APIRouter(prefix="/trips", tags=["trip"])


def _load_trip(conn, trip_id: str):
    row = conn.execute(
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
        WHERE t.trip_id = ?
        """,
        (trip_id,),
    ).fetchone()
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="行程不存在")
    return row


def _ensure_owned(row, user: dict) -> None:
    if row["user_id"] != user["user_id"]:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="无权访问该行程")


def _quote_from_db(conn, *, train_no: str, travel_date: str, seat_type_id: str) -> QuoteOut:
    train = conn.execute(
        "SELECT train_no FROM trains WHERE train_no = ?",
        (train_no,),
    ).fetchone()
    if train is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="车次不存在")

    seat = conn.execute(
        "SELECT * FROM seat_types WHERE seat_type_id = ? AND train_no = ?",
        (seat_type_id, train_no),
    ).fetchone()
    if seat is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="席别不存在")

    inv = conn.execute(
        """
        SELECT available_count, price
        FROM inventory
        WHERE train_no = ? AND travel_date = ? AND seat_type_id = ?
        """,
        (train_no, travel_date, seat_type_id),
    ).fetchone()
    if inv is None or inv["available_count"] <= 0:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="余票不足")

    ticket_price = float(inv["price"])
    total_price = round(ticket_price + SERVICE_FEE, 2)
    return QuoteOut(
        train_no=train_no,
        travel_date=travel_date,
        seat_type_id=seat_type_id,
        ticket_price=ticket_price,
        service_fee=SERVICE_FEE,
        total_price=total_price,
    )


@router.post("/quote", response_model=QuoteOut)
def quote_trip(body: QuoteRequest) -> QuoteOut:
    with connect() as conn:
        return _quote_from_db(
            conn,
            train_no=body.train_no,
            travel_date=body.travel_date,
            seat_type_id=body.seat_type_id,
        )


@router.post("", response_model=TripOut, status_code=status.HTTP_201_CREATED)
def create_trip(
    body: TripCreateRequest,
    user: dict = Depends(get_current_user),
) -> TripOut:
    with connect() as conn:
        quote = _quote_from_db(
            conn,
            train_no=body.train_no,
            travel_date=body.travel_date,
            seat_type_id=body.seat_type_id,
        )
        train = conn.execute(
            "SELECT from_station_id, to_station_id FROM trains WHERE train_no = ?",
            (body.train_no,),
        ).fetchone()
        trip_id = new_trip_id()
        timestamp = now_iso()
        conn.execute(
            """
            INSERT INTO trips (
                trip_id, user_id, train_no, travel_date, seat_type_id,
                passenger_name, passenger_phone, from_station_id, to_station_id,
                status, ticket_price, service_fee, total_price, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                trip_id,
                user["user_id"],
                body.train_no,
                body.travel_date,
                body.seat_type_id,
                body.passenger_name,
                body.passenger_phone,
                train["from_station_id"],
                train["to_station_id"],
                "confirmed",
                quote.ticket_price,
                quote.service_fee,
                quote.total_price,
                timestamp,
                timestamp,
            ),
        )
        conn.execute(
            """
            UPDATE inventory
            SET available_count = available_count - 1
            WHERE train_no = ? AND travel_date = ? AND seat_type_id = ?
            """,
            (body.train_no, body.travel_date, body.seat_type_id),
        )
        conn.execute(
            """
            INSERT INTO trip_events (trip_id, status, note, created_at)
            VALUES (?, ?, ?, ?)
            """,
            (trip_id, "confirmed", "行程已出票", timestamp),
        )
        conn.commit()
        row = _load_trip(conn, trip_id)
    return TripOut(**row_to_trip(row))


@router.get("", response_model=list[TripOut])
def list_trips(
    status_filter: str | None = Query(default=None, alias="status"),
    from_date: str | None = Query(default=None, description="乘车日起 YYYY-MM-DD"),
    user: dict = Depends(get_current_user),
) -> list[TripOut]:
    sql = """
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
    """
    params: list[str] = [user["user_id"]]
    if status_filter:
        sql += " AND t.status = ?"
        params.append(status_filter)
    if from_date:
        sql += " AND t.travel_date >= ?"
        params.append(from_date)
    sql += " ORDER BY t.created_at DESC"

    with connect() as conn:
        rows = conn.execute(sql, params).fetchall()
    return [TripOut(**row_to_trip(row)) for row in rows]


@router.get("/{trip_id}", response_model=TripOut)
def get_trip(
    trip_id: str,
    user: dict = Depends(get_current_user),
) -> TripOut:
    with connect() as conn:
        row = _load_trip(conn, trip_id)
        _ensure_owned(row, user)
    return TripOut(**row_to_trip(row))


@router.get("/{trip_id}/price-breakdown", response_model=PriceBreakdownOut)
def get_price_breakdown(
    trip_id: str,
    user: dict = Depends(get_current_user),
) -> PriceBreakdownOut:
    with connect() as conn:
        row = _load_trip(conn, trip_id)
        _ensure_owned(row, user)
    return PriceBreakdownOut(
        trip_id=row["trip_id"],
        ticket_price=row["ticket_price"],
        service_fee=row["service_fee"],
        total_price=row["total_price"],
    )


@router.patch("/{trip_id}/passenger-info", response_model=TripOut)
def update_passenger_info(
    trip_id: str,
    body: PassengerInfoUpdateRequest,
    user: dict = Depends(get_current_user),
) -> TripOut:
    if body.passenger_name is None and body.passenger_phone is None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="至少提供一个字段")

    with connect() as conn:
        row = _load_trip(conn, trip_id)
        _ensure_owned(row, user)
        if row["status"] == "cancelled":
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="行程已取消")

        passenger_name = body.passenger_name or row["passenger_name"]
        passenger_phone = body.passenger_phone or row["passenger_phone"]
        updated_at = now_iso()
        conn.execute(
            """
            UPDATE trips
            SET passenger_name = ?, passenger_phone = ?, updated_at = ?
            WHERE trip_id = ?
            """,
            (passenger_name, passenger_phone, updated_at, trip_id),
        )
        conn.execute(
            """
            INSERT INTO trip_events (trip_id, status, note, created_at)
            VALUES (?, ?, ?, ?)
            """,
            (trip_id, row["status"], "更新旅客信息", updated_at),
        )
        conn.commit()
        row = _load_trip(conn, trip_id)
    return TripOut(**row_to_trip(row))


@router.post("/{trip_id}/cancel", response_model=CancelOut)
def cancel_trip(
    trip_id: str,
    user: dict = Depends(get_current_user),
) -> CancelOut:
    with connect() as conn:
        row = _load_trip(conn, trip_id)
        _ensure_owned(row, user)
        if row["status"] == "cancelled":
            return CancelOut(
                trip_id=trip_id,
                status="cancelled",
                message="行程已是取消状态",
            )

        updated_at = now_iso()
        conn.execute(
            """
            UPDATE trips
            SET status = 'cancelled', updated_at = ?
            WHERE trip_id = ?
            """,
            (updated_at, trip_id),
        )
        conn.execute(
            """
            UPDATE inventory
            SET available_count = available_count + 1
            WHERE train_no = ? AND travel_date = ? AND seat_type_id = ?
            """,
            (row["train_no"], row["travel_date"], row["seat_type_id"]),
        )
        conn.execute(
            """
            INSERT INTO trip_events (trip_id, status, note, created_at)
            VALUES (?, ?, ?, ?)
            """,
            (trip_id, "cancelled", "行程已取消", updated_at),
        )
        conn.commit()

    return CancelOut(
        trip_id=trip_id,
        status="cancelled",
        message="行程取消成功，余票已恢复",
    )


@router.get("/{trip_id}/timeline", response_model=TripTimelineOut)
def get_trip_timeline(
    trip_id: str,
    user: dict = Depends(get_current_user),
) -> TripTimelineOut:
    with connect() as conn:
        row = _load_trip(conn, trip_id)
        _ensure_owned(row, user)
        events = conn.execute(
            """
            SELECT status, note, created_at
            FROM trip_events
            WHERE trip_id = ?
            ORDER BY id
            """,
            (trip_id,),
        ).fetchall()
    return TripTimelineOut(
        trip_id=trip_id,
        events=[
            TripEventOut(
                status=event["status"],
                note=event["note"],
                created_at=event["created_at"],
            )
            for event in events
        ],
    )
