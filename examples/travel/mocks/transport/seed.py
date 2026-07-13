"""Seed demo data for the transport mock."""

from __future__ import annotations

from datetime import date, timedelta

from .db import connect, init_db

DEMO_USERNAME = "HubloomTransport"
DEMO_PASSWORD = "HubloomTransport@2026"
DEMO_TOKEN = "demo-transport-token"
DEMO_USER_ID = "U-HUBLOOM-TRANSPORT"


def seed_if_empty() -> None:
    init_db()
    with connect() as conn:
        row = conn.execute("SELECT COUNT(*) AS c FROM users").fetchone()
        if row and row["c"] > 0:
            return

        conn.execute(
            """
            INSERT INTO users (user_id, username, password, display_name, phone, email, token)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                DEMO_USER_ID,
                DEMO_USERNAME,
                DEMO_PASSWORD,
                "Hubloom 交通演示账号",
                "13800000001",
                "hubloom-transport@example.com",
                DEMO_TOKEN,
            ),
        )

        stations = [
            ("ST-SHH", "上海虹桥", "上海", "SHH"),
            ("ST-BJN", "北京南", "北京", "BJN"),
            ("ST-NJN", "南京南", "南京", "NJN"),
            ("ST-TJN", "天津南", "天津", "TJN"),
        ]
        conn.executemany(
            "INSERT INTO stations (station_id, name, city, code) VALUES (?, ?, ?, ?)",
            stations,
        )

        trains = [
            (
                "G1234",
                "高铁",
                "ST-SHH",
                "ST-BJN",
                "14:00",
                "19:00",
                300,
                "上海虹桥开往北京南，途经南京南、天津南。",
            ),
            (
                "G5678",
                "高铁",
                "ST-BJN",
                "ST-SHH",
                "09:00",
                "14:10",
                310,
                "北京南开往上海虹桥。",
            ),
            (
                "D9012",
                "动车",
                "ST-SHH",
                "ST-NJN",
                "08:30",
                "10:15",
                105,
                "上海虹桥开往南京南的短途动车。",
            ),
        ]
        conn.executemany(
            """
            INSERT INTO trains (
                train_no, train_type, from_station_id, to_station_id,
                depart_time, arrive_time, duration_minutes, description
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            trains,
        )

        stops = [
            ("G1234", "ST-SHH", 1, None, "14:00"),
            ("G1234", "ST-NJN", 2, "16:05", "16:10"),
            ("G1234", "ST-TJN", 3, "18:20", "18:25"),
            ("G1234", "ST-BJN", 4, "19:00", None),
            ("G5678", "ST-BJN", 1, None, "09:00"),
            ("G5678", "ST-TJN", 2, "10:40", "10:45"),
            ("G5678", "ST-NJN", 3, "12:50", "12:55"),
            ("G5678", "ST-SHH", 4, "14:10", None),
        ]
        conn.executemany(
            """
            INSERT INTO train_stops (train_no, station_id, stop_order, arrive_time, depart_time)
            VALUES (?, ?, ?, ?, ?)
            """,
            stops,
        )

        seat_types = [
            ("SEAT-G1234-2ND", "G1234", "二等座", 553.0, "标准二等座。"),
            ("SEAT-G1234-1ST", "G1234", "一等座", 884.0, "更宽敞的一等座。"),
            ("SEAT-G5678-2ND", "G5678", "二等座", 553.0, "标准二等座。"),
            ("SEAT-D9012-2ND", "D9012", "二等座", 145.0, "动车二等座。"),
        ]
        conn.executemany(
            """
            INSERT INTO seat_types (seat_type_id, train_no, name, price, description)
            VALUES (?, ?, ?, ?, ?)
            """,
            seat_types,
        )

        start = date(2026, 7, 10)
        end = date(2026, 7, 20)
        inventory_rows = []
        for seat_type_id, train_no, _name, price, _desc in seat_types:
            current = start
            while current <= end:
                inventory_rows.append(
                    (train_no, current.isoformat(), seat_type_id, 120, float(price))
                )
                current += timedelta(days=1)
        conn.executemany(
            """
            INSERT INTO inventory (train_no, travel_date, seat_type_id, available_count, price)
            VALUES (?, ?, ?, ?, ?)
            """,
            inventory_rows,
        )

        conn.execute(
            """
            INSERT INTO train_status (
                train_no, travel_date, status,
                planned_departure, planned_arrival,
                actual_departure, estimated_arrival,
                delay_minutes, reason
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "G1234",
                "2026-07-13",
                "delayed",
                "2026-07-13 14:00",
                "2026-07-13 19:00",
                "2026-07-13 17:00",
                "2026-07-13 22:00",
                180,
                "线路设备检查，列车晚点出发。",
            ),
        )

        trip_id = "TRIP-5566"
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
                DEMO_USER_ID,
                "G1234",
                "2026-07-13",
                "SEAT-G1234-2ND",
                "张三",
                "13800001111",
                "ST-SHH",
                "ST-BJN",
                "delayed",
                553.0,
                15.0,
                568.0,
                "2026-07-10T10:00:00",
                "2026-07-13T17:05:00",
            ),
        )

        conn.execute(
            """
            UPDATE inventory
            SET available_count = available_count - 1
            WHERE train_no = ? AND travel_date = ? AND seat_type_id = ?
            """,
            ("G1234", "2026-07-13", "SEAT-G1234-2ND"),
        )

        events = [
            (trip_id, "confirmed", "行程已出票", "2026-07-10T10:00:00"),
            (trip_id, "delayed", "车次 G1234 延误 180 分钟", "2026-07-13T17:05:00"),
        ]
        conn.executemany(
            """
            INSERT INTO trip_events (trip_id, status, note, created_at)
            VALUES (?, ?, ?, ?)
            """,
            events,
        )

        conn.commit()
