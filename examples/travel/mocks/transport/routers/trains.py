"""Train routes."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query, status

from ..db import connect
from ..schemas import (
    AvailabilityItem,
    AvailabilityOut,
    SeatTypeOut,
    TrainDetail,
    TrainStatusOut,
    TrainStopOut,
    TrainSummary,
)

router = APIRouter(prefix="/trains", tags=["train"])


def _station_name(conn, station_id: str) -> str:
    row = conn.execute(
        "SELECT name FROM stations WHERE station_id = ?",
        (station_id,),
    ).fetchone()
    return row["name"] if row else station_id


def _train_summary(conn, row) -> TrainSummary:
    return TrainSummary(
        train_no=row["train_no"],
        train_type=row["train_type"],
        from_station_id=row["from_station_id"],
        from_station_name=_station_name(conn, row["from_station_id"]),
        to_station_id=row["to_station_id"],
        to_station_name=_station_name(conn, row["to_station_id"]),
        depart_time=row["depart_time"],
        arrive_time=row["arrive_time"],
        duration_minutes=row["duration_minutes"],
    )


def _get_train_or_404(conn, train_no: str):
    row = conn.execute(
        "SELECT * FROM trains WHERE train_no = ?",
        (train_no,),
    ).fetchone()
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="车次不存在")
    return row


@router.get("", response_model=list[TrainSummary])
def list_trains(
    date: str | None = Query(default=None, description="运行日期 YYYY-MM-DD"),
) -> list[TrainSummary]:
    with connect() as conn:
        rows = conn.execute("SELECT * FROM trains ORDER BY train_no").fetchall()
        return [_train_summary(conn, row) for row in rows]


@router.get("/search", response_model=list[TrainSummary])
def search_trains(
    from_station: str = Query(..., description="出发站 ID 或名称关键词"),
    to_station: str = Query(..., description="到达站 ID 或名称关键词"),
    date: str | None = Query(default=None),
) -> list[TrainSummary]:
    from_key = f"%{from_station.strip()}%"
    to_key = f"%{to_station.strip()}%"
    with connect() as conn:
        rows = conn.execute(
            """
            SELECT t.*
            FROM trains t
            JOIN stations fs ON fs.station_id = t.from_station_id
            JOIN stations ts ON ts.station_id = t.to_station_id
            WHERE (fs.station_id LIKE ? OR fs.name LIKE ? OR fs.city LIKE ?)
              AND (ts.station_id LIKE ? OR ts.name LIKE ? OR ts.city LIKE ?)
            ORDER BY t.train_no
            """,
            (from_key, from_key, from_key, to_key, to_key, to_key),
        ).fetchall()
        return [_train_summary(conn, row) for row in rows]


@router.get("/{train_no}", response_model=TrainDetail)
def get_train(train_no: str) -> TrainDetail:
    with connect() as conn:
        row = _get_train_or_404(conn, train_no)
        stop_rows = conn.execute(
            """
            SELECT ts.stop_order, ts.arrive_time, ts.depart_time,
                   s.station_id, s.name AS station_name
            FROM train_stops ts
            JOIN stations s ON s.station_id = ts.station_id
            WHERE ts.train_no = ?
            ORDER BY ts.stop_order
            """,
            (train_no,),
        ).fetchall()
        summary = _train_summary(conn, row)
        stops = [
            TrainStopOut(
                station_id=stop["station_id"],
                station_name=stop["station_name"],
                stop_order=stop["stop_order"],
                arrive_time=stop["arrive_time"],
                depart_time=stop["depart_time"],
            )
            for stop in stop_rows
        ]
    return TrainDetail(**summary.model_dump(), description=row["description"], stops=stops)


@router.get("/{train_no}/status", response_model=TrainStatusOut)
def get_train_status(
    train_no: str,
    date: str = Query(..., description="运行日期 YYYY-MM-DD"),
) -> TrainStatusOut:
    with connect() as conn:
        _get_train_or_404(conn, train_no)
        row = conn.execute(
            """
            SELECT * FROM train_status
            WHERE train_no = ? AND travel_date = ?
            """,
            (train_no, date),
        ).fetchone()
        if row is None:
            train = conn.execute(
                "SELECT depart_time, arrive_time FROM trains WHERE train_no = ?",
                (train_no,),
            ).fetchone()
            return TrainStatusOut(
                train_no=train_no,
                travel_date=date,
                status="on_time",
                planned_departure=f"{date} {train['depart_time']}",
                planned_arrival=f"{date} {train['arrive_time']}",
                actual_departure=None,
                estimated_arrival=None,
                delay_minutes=0,
                reason=None,
            )
    return TrainStatusOut(
        train_no=row["train_no"],
        travel_date=row["travel_date"],
        status=row["status"],
        planned_departure=row["planned_departure"],
        planned_arrival=row["planned_arrival"],
        actual_departure=row["actual_departure"],
        estimated_arrival=row["estimated_arrival"],
        delay_minutes=row["delay_minutes"],
        reason=row["reason"],
    )


@router.get("/{train_no}/seat-types", response_model=list[SeatTypeOut])
def list_seat_types(train_no: str) -> list[SeatTypeOut]:
    with connect() as conn:
        _get_train_or_404(conn, train_no)
        rows = conn.execute(
            "SELECT * FROM seat_types WHERE train_no = ? ORDER BY seat_type_id",
            (train_no,),
        ).fetchall()
    return [
        SeatTypeOut(
            seat_type_id=row["seat_type_id"],
            train_no=row["train_no"],
            name=row["name"],
            price=row["price"],
            description=row["description"],
        )
        for row in rows
    ]


@router.get("/{train_no}/availability", response_model=AvailabilityOut)
def get_availability(
    train_no: str,
    date: str = Query(..., description="乘车日期 YYYY-MM-DD"),
    seat_type_id: str | None = Query(default=None),
) -> AvailabilityOut:
    with connect() as conn:
        _get_train_or_404(conn, train_no)
        if seat_type_id:
            seat_rows = conn.execute(
                "SELECT * FROM seat_types WHERE seat_type_id = ? AND train_no = ?",
                (seat_type_id, train_no),
            ).fetchall()
        else:
            seat_rows = conn.execute(
                "SELECT * FROM seat_types WHERE train_no = ? ORDER BY seat_type_id",
                (train_no,),
            ).fetchall()

        items: list[AvailabilityItem] = []
        for seat in seat_rows:
            inv = conn.execute(
                """
                SELECT available_count, price
                FROM inventory
                WHERE train_no = ? AND travel_date = ? AND seat_type_id = ?
                """,
                (train_no, date, seat["seat_type_id"]),
            ).fetchone()
            if inv is None:
                items.append(
                    AvailabilityItem(
                        seat_type_id=seat["seat_type_id"],
                        seat_type_name=seat["name"],
                        available=False,
                        available_count=0,
                        price=seat["price"],
                    )
                )
            else:
                items.append(
                    AvailabilityItem(
                        seat_type_id=seat["seat_type_id"],
                        seat_type_name=seat["name"],
                        available=inv["available_count"] > 0,
                        available_count=inv["available_count"],
                        price=inv["price"],
                    )
                )

    return AvailabilityOut(train_no=train_no, travel_date=date, items=items)
