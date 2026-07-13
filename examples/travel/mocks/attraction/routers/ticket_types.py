"""Ticket type and availability routes."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query, status

from ..db import connect
from ..schemas import AvailabilityItem, AvailabilityOut, TicketTypeDetail, TicketTypeSummary

router = APIRouter(tags=["ticket_type"])


def _ticket_type_summary(row) -> TicketTypeSummary:
    return TicketTypeSummary(
        ticket_type_id=row["ticket_type_id"],
        attraction_id=row["attraction_id"],
        name=row["name"],
        audience=row["audience"],
        base_price=row["base_price"],
    )


def _get_ticket_type_or_404(conn, ticket_type_id: str):
    row = conn.execute(
        "SELECT * FROM ticket_types WHERE ticket_type_id = ?",
        (ticket_type_id,),
    ).fetchone()
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="票种不存在")
    return row


@router.get("/attractions/{attraction_id}/ticket-types", response_model=list[TicketTypeSummary])
def list_ticket_types(attraction_id: str) -> list[TicketTypeSummary]:
    with connect() as conn:
        attraction = conn.execute(
            "SELECT attraction_id FROM attractions WHERE attraction_id = ?",
            (attraction_id,),
        ).fetchone()
        if attraction is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="景区不存在")
        rows = conn.execute(
            "SELECT * FROM ticket_types WHERE attraction_id = ? ORDER BY ticket_type_id",
            (attraction_id,),
        ).fetchall()
    return [_ticket_type_summary(row) for row in rows]


@router.get("/ticket-types/{ticket_type_id}", response_model=TicketTypeDetail)
def get_ticket_type(ticket_type_id: str) -> TicketTypeDetail:
    with connect() as conn:
        row = _get_ticket_type_or_404(conn, ticket_type_id)
    summary = _ticket_type_summary(row)
    return TicketTypeDetail(**summary.model_dump(), description=row["description"])


@router.get("/attractions/{attraction_id}/availability", response_model=AvailabilityOut)
def get_availability(
    attraction_id: str,
    date: str = Query(..., description="参观日期 YYYY-MM-DD"),
    ticket_type_id: str | None = Query(default=None),
) -> AvailabilityOut:
    with connect() as conn:
        attraction = conn.execute(
            "SELECT attraction_id FROM attractions WHERE attraction_id = ?",
            (attraction_id,),
        ).fetchone()
        if attraction is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="景区不存在")

        if ticket_type_id:
            ticket_row = _get_ticket_type_or_404(conn, ticket_type_id)
            if ticket_row["attraction_id"] != attraction_id:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="票种不属于该景区",
                )
            ticket_rows = [ticket_row]
        else:
            ticket_rows = conn.execute(
                "SELECT * FROM ticket_types WHERE attraction_id = ? ORDER BY ticket_type_id",
                (attraction_id,),
            ).fetchall()

        items: list[AvailabilityItem] = []
        for ticket in ticket_rows:
            inv_rows = conn.execute(
                """
                SELECT entry_slot, available_count, price
                FROM inventory
                WHERE attraction_id = ? AND ticket_type_id = ? AND visit_date = ?
                ORDER BY entry_slot
                """,
                (attraction_id, ticket["ticket_type_id"], date),
            ).fetchall()
            for inv in inv_rows:
                items.append(
                    AvailabilityItem(
                        ticket_type_id=ticket["ticket_type_id"],
                        ticket_type_name=ticket["name"],
                        entry_slot=inv["entry_slot"],
                        available=inv["available_count"] > 0,
                        available_count=inv["available_count"],
                        price=inv["price"],
                    )
                )

    return AvailabilityOut(attraction_id=attraction_id, visit_date=date, items=items)
