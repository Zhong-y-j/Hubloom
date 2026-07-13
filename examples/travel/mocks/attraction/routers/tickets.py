"""Ticket booking routes."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, status

from ..db import connect
from ..deps import get_current_user
from ..schemas import (
    CancelOut,
    PriceBreakdownOut,
    QuoteOut,
    QuoteRequest,
    TicketCreateRequest,
    TicketEventOut,
    TicketOut,
    TicketTimelineOut,
    VisitorInfoUpdateRequest,
)
from ..utils import SERVICE_FEE, new_ticket_id, now_iso, row_to_ticket

router = APIRouter(prefix="/tickets", tags=["ticket"])


def _load_ticket(conn, ticket_id: str):
    row = conn.execute(
        """
        SELECT t.*, a.name AS attraction_name, tt.name AS ticket_type_name
        FROM tickets t
        JOIN attractions a ON a.attraction_id = t.attraction_id
        JOIN ticket_types tt ON tt.ticket_type_id = t.ticket_type_id
        WHERE t.ticket_id = ?
        """,
        (ticket_id,),
    ).fetchone()
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="门票不存在")
    return row


def _ensure_owned(row, user: dict) -> None:
    if row["user_id"] != user["user_id"]:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="无权访问该门票")


def _quote_from_db(
    conn,
    *,
    attraction_id: str,
    ticket_type_id: str,
    visit_date: str,
    entry_slot: str,
) -> QuoteOut:
    attraction = conn.execute(
        "SELECT attraction_id FROM attractions WHERE attraction_id = ?",
        (attraction_id,),
    ).fetchone()
    if attraction is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="景区不存在")

    ticket_type = conn.execute(
        "SELECT * FROM ticket_types WHERE ticket_type_id = ? AND attraction_id = ?",
        (ticket_type_id, attraction_id),
    ).fetchone()
    if ticket_type is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="票种不存在")

    inv = conn.execute(
        """
        SELECT available_count, price
        FROM inventory
        WHERE attraction_id = ? AND ticket_type_id = ? AND visit_date = ? AND entry_slot = ?
        """,
        (attraction_id, ticket_type_id, visit_date, entry_slot),
    ).fetchone()
    if inv is None or inv["available_count"] <= 0:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="该时段余票不足")

    ticket_price = float(inv["price"])
    total_price = round(ticket_price + SERVICE_FEE, 2)
    return QuoteOut(
        attraction_id=attraction_id,
        ticket_type_id=ticket_type_id,
        visit_date=visit_date,
        entry_slot=entry_slot,
        ticket_price=ticket_price,
        service_fee=SERVICE_FEE,
        total_price=total_price,
    )


@router.post("/quote", response_model=QuoteOut)
def quote_ticket(body: QuoteRequest) -> QuoteOut:
    with connect() as conn:
        return _quote_from_db(
            conn,
            attraction_id=body.attraction_id,
            ticket_type_id=body.ticket_type_id,
            visit_date=body.visit_date,
            entry_slot=body.entry_slot,
        )


@router.post("", response_model=TicketOut, status_code=status.HTTP_201_CREATED)
def create_ticket(
    body: TicketCreateRequest,
    user: dict = Depends(get_current_user),
) -> TicketOut:
    with connect() as conn:
        quote = _quote_from_db(
            conn,
            attraction_id=body.attraction_id,
            ticket_type_id=body.ticket_type_id,
            visit_date=body.visit_date,
            entry_slot=body.entry_slot,
        )
        ticket_id = new_ticket_id()
        timestamp = now_iso()
        conn.execute(
            """
            INSERT INTO tickets (
                ticket_id, user_id, attraction_id, ticket_type_id, trip_id,
                visitor_name, visitor_phone, visit_date, entry_slot, status,
                ticket_price, service_fee, total_price, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                ticket_id,
                user["user_id"],
                body.attraction_id,
                body.ticket_type_id,
                body.trip_id,
                body.visitor_name,
                body.visitor_phone,
                body.visit_date,
                body.entry_slot,
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
            WHERE attraction_id = ? AND ticket_type_id = ? AND visit_date = ? AND entry_slot = ?
            """,
            (
                body.attraction_id,
                body.ticket_type_id,
                body.visit_date,
                body.entry_slot,
            ),
        )
        conn.execute(
            """
            INSERT INTO ticket_events (ticket_id, status, note, created_at)
            VALUES (?, ?, ?, ?)
            """,
            (ticket_id, "confirmed", "门票预约成功", timestamp),
        )
        conn.commit()
        row = _load_ticket(conn, ticket_id)
    return TicketOut(**row_to_ticket(row))


@router.get("", response_model=list[TicketOut])
def list_tickets(
    status_filter: str | None = Query(default=None, alias="status"),
    from_date: str | None = Query(default=None, description="参观日起 YYYY-MM-DD"),
    user: dict = Depends(get_current_user),
) -> list[TicketOut]:
    sql = """
        SELECT t.*, a.name AS attraction_name, tt.name AS ticket_type_name
        FROM tickets t
        JOIN attractions a ON a.attraction_id = t.attraction_id
        JOIN ticket_types tt ON tt.ticket_type_id = t.ticket_type_id
        WHERE t.user_id = ?
    """
    params: list[str] = [user["user_id"]]
    if status_filter:
        sql += " AND t.status = ?"
        params.append(status_filter)
    if from_date:
        sql += " AND t.visit_date >= ?"
        params.append(from_date)
    sql += " ORDER BY t.created_at DESC"

    with connect() as conn:
        rows = conn.execute(sql, params).fetchall()
    return [TicketOut(**row_to_ticket(row)) for row in rows]


@router.get("/by-trip/{trip_id}", response_model=list[TicketOut])
def list_tickets_by_trip(
    trip_id: str,
    user: dict = Depends(get_current_user),
) -> list[TicketOut]:
    with connect() as conn:
        rows = conn.execute(
            """
            SELECT t.*, a.name AS attraction_name, tt.name AS ticket_type_name
            FROM tickets t
            JOIN attractions a ON a.attraction_id = t.attraction_id
            JOIN ticket_types tt ON tt.ticket_type_id = t.ticket_type_id
            WHERE t.user_id = ? AND t.trip_id = ?
            ORDER BY t.created_at DESC
            """,
            (user["user_id"], trip_id),
        ).fetchall()
    return [TicketOut(**row_to_ticket(row)) for row in rows]


@router.get("/{ticket_id}", response_model=TicketOut)
def get_ticket(
    ticket_id: str,
    user: dict = Depends(get_current_user),
) -> TicketOut:
    with connect() as conn:
        row = _load_ticket(conn, ticket_id)
        _ensure_owned(row, user)
    return TicketOut(**row_to_ticket(row))


@router.get("/{ticket_id}/price-breakdown", response_model=PriceBreakdownOut)
def get_price_breakdown(
    ticket_id: str,
    user: dict = Depends(get_current_user),
) -> PriceBreakdownOut:
    with connect() as conn:
        row = _load_ticket(conn, ticket_id)
        _ensure_owned(row, user)
    return PriceBreakdownOut(
        ticket_id=row["ticket_id"],
        ticket_price=row["ticket_price"],
        service_fee=row["service_fee"],
        total_price=row["total_price"],
    )


@router.patch("/{ticket_id}/visitor-info", response_model=TicketOut)
def update_visitor_info(
    ticket_id: str,
    body: VisitorInfoUpdateRequest,
    user: dict = Depends(get_current_user),
) -> TicketOut:
    if body.visitor_name is None and body.visitor_phone is None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="至少提供一个字段")

    with connect() as conn:
        row = _load_ticket(conn, ticket_id)
        _ensure_owned(row, user)
        if row["status"] == "cancelled":
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="门票已取消")

        visitor_name = body.visitor_name or row["visitor_name"]
        visitor_phone = body.visitor_phone or row["visitor_phone"]
        updated_at = now_iso()
        conn.execute(
            """
            UPDATE tickets
            SET visitor_name = ?, visitor_phone = ?, updated_at = ?
            WHERE ticket_id = ?
            """,
            (visitor_name, visitor_phone, updated_at, ticket_id),
        )
        conn.execute(
            """
            INSERT INTO ticket_events (ticket_id, status, note, created_at)
            VALUES (?, ?, ?, ?)
            """,
            (ticket_id, row["status"], "更新游客信息", updated_at),
        )
        conn.commit()
        row = _load_ticket(conn, ticket_id)
    return TicketOut(**row_to_ticket(row))


@router.post("/{ticket_id}/cancel", response_model=CancelOut)
def cancel_ticket(
    ticket_id: str,
    user: dict = Depends(get_current_user),
) -> CancelOut:
    with connect() as conn:
        row = _load_ticket(conn, ticket_id)
        _ensure_owned(row, user)
        if row["status"] == "cancelled":
            return CancelOut(
                ticket_id=ticket_id,
                status="cancelled",
                message="门票已是取消状态",
            )

        updated_at = now_iso()
        conn.execute(
            """
            UPDATE tickets
            SET status = 'cancelled', updated_at = ?
            WHERE ticket_id = ?
            """,
            (updated_at, ticket_id),
        )
        conn.execute(
            """
            UPDATE inventory
            SET available_count = available_count + 1
            WHERE attraction_id = ? AND ticket_type_id = ? AND visit_date = ? AND entry_slot = ?
            """,
            (
                row["attraction_id"],
                row["ticket_type_id"],
                row["visit_date"],
                row["entry_slot"],
            ),
        )
        conn.execute(
            """
            INSERT INTO ticket_events (ticket_id, status, note, created_at)
            VALUES (?, ?, ?, ?)
            """,
            (ticket_id, "cancelled", "门票已取消", updated_at),
        )
        conn.commit()

    return CancelOut(
        ticket_id=ticket_id,
        status="cancelled",
        message="门票取消成功，余票已恢复",
    )


@router.get("/{ticket_id}/timeline", response_model=TicketTimelineOut)
def get_ticket_timeline(
    ticket_id: str,
    user: dict = Depends(get_current_user),
) -> TicketTimelineOut:
    with connect() as conn:
        row = _load_ticket(conn, ticket_id)
        _ensure_owned(row, user)
        events = conn.execute(
            """
            SELECT status, note, created_at
            FROM ticket_events
            WHERE ticket_id = ?
            ORDER BY id
            """,
            (ticket_id,),
        ).fetchall()
    return TicketTimelineOut(
        ticket_id=ticket_id,
        events=[
            TicketEventOut(
                status=event["status"],
                note=event["note"],
                created_at=event["created_at"],
            )
            for event in events
        ],
    )
