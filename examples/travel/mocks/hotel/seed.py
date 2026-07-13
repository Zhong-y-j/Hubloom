"""Seed demo data for the hotel mock."""

from __future__ import annotations

from datetime import date, timedelta

from .db import connect, init_db

DEMO_USERNAME = "HubloomHotel"
DEMO_PASSWORD = "HubloomHotel@2026"
DEMO_TOKEN = "demo-hotel-token"
DEMO_USER_ID = "U-HUBLOOM-HOTEL"


def _date_str(d: date) -> str:
    return d.isoformat()


def _daterange(start: date, end: date) -> list[date]:
    days: list[date] = []
    current = start
    while current < end:
        days.append(current)
        current += timedelta(days=1)
    return days


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
                "Hubloom 酒店演示账号",
                "13800000000",
                "hubloom-hotel@example.com",
                DEMO_TOKEN,
            ),
        )

        hotels = [
            (
                "HOTEL-BJ-01",
                "北京王府井商务酒店",
                "北京",
                "东城区王府井大街 88 号",
                "010-88886666",
                "毗邻王府井步行街，适合商务与旅游入住。",
                "14:00",
                "12:00",
                "20:00",
                "入住日前 18:00 前可免费取消。",
                "办理入住请携带身份证件；20:00 前到店可保留房间。",
            ),
            (
                "HOTEL-BJ-02",
                "北京南站快捷酒店",
                "北京",
                "丰台区北京南站东路 16 号",
                "010-66667777",
                "靠近北京南站，适合中转和早班高铁旅客。",
                "15:00",
                "11:00",
                "22:00",
                "入住日前 12:00 前可免费取消。",
                "晚到请提前联系前台。",
            ),
            (
                "HOTEL-BJ-03",
                "故宫文化主题客栈",
                "北京",
                "东城区景山前街 12 号",
                "010-55558888",
                "步行可达故宫，适合文化体验型旅客。",
                "14:00",
                "12:00",
                "19:00",
                "入住日前 24 小时前可免费取消。",
                "客栈不含早餐，请自行安排行程。",
            ),
        ]
        conn.executemany(
            """
            INSERT INTO hotels (
                hotel_id, name, city, address, phone, description,
                check_in_time, check_out_time, late_arrival_hold_until,
                cancellation_policy, check_in_note
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            hotels,
        )

        facilities = [
            ("HOTEL-BJ-01", "免费 WiFi"),
            ("HOTEL-BJ-01", "自助早餐"),
            ("HOTEL-BJ-01", "健身房"),
            ("HOTEL-BJ-01", "停车场"),
            ("HOTEL-BJ-02", "免费 WiFi"),
            ("HOTEL-BJ-02", "行李寄存"),
            ("HOTEL-BJ-02", "24 小时前台"),
            ("HOTEL-BJ-03", "免费 WiFi"),
            ("HOTEL-BJ-03", "旅游咨询"),
            ("HOTEL-BJ-03", "汉服体验"),
        ]
        conn.executemany(
            "INSERT INTO hotel_facilities (hotel_id, name) VALUES (?, ?)",
            facilities,
        )

        reviews = [
            ("HOTEL-BJ-01", "李女士", 4.6, "位置很好，去故宫方便。"),
            ("HOTEL-BJ-01", "王先生", 4.4, "房间整洁，前台响应及时。"),
            ("HOTEL-BJ-02", "赵同学", 4.2, "赶高铁很省时，性价比高。"),
            ("HOTEL-BJ-03", "旅行达人阿南", 4.8, "文化氛围浓，适合拍照。"),
        ]
        conn.executemany(
            """
            INSERT INTO hotel_reviews (hotel_id, author, rating, comment)
            VALUES (?, ?, ?, ?)
            """,
            reviews,
        )

        room_types = [
            (
                "RT-BJ-01-STD",
                "HOTEL-BJ-01",
                "标准大床房",
                "大床 1.8m",
                28.0,
                2,
                468.0,
                "城市景观，含双早。",
            ),
            (
                "RT-BJ-01-DLX",
                "HOTEL-BJ-01",
                "豪华双床房",
                "双床 1.2m",
                32.0,
                2,
                528.0,
                "更大空间，适合同行旅客。",
            ),
            (
                "RT-BJ-02-ECO",
                "HOTEL-BJ-02",
                "快捷单人房",
                "单人床 1.2m",
                18.0,
                1,
                298.0,
                "适合短途中转。",
            ),
            (
                "RT-BJ-03-CUL",
                "HOTEL-BJ-03",
                "文化庭院房",
                "大床 1.5m",
                24.0,
                2,
                398.0,
                "庭院景观，靠近故宫北门。",
            ),
        ]
        conn.executemany(
            """
            INSERT INTO room_types (
                room_type_id, hotel_id, name, bed_type, area_sqm,
                max_guests, base_price, description
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            room_types,
        )

        start = date(2026, 7, 10)
        end = date(2026, 7, 25)
        inventory_rows = []
        for room_type_id, hotel_id, *_rest, base_price, _description in room_types:
            for stay_day in _daterange(start, end):
                inventory_rows.append(
                    (
                        hotel_id,
                        room_type_id,
                        _date_str(stay_day),
                        5,
                        float(base_price),
                    )
                )
        conn.executemany(
            """
            INSERT INTO inventory (hotel_id, room_type_id, stay_date, available_count, price)
            VALUES (?, ?, ?, ?, ?)
            """,
            inventory_rows,
        )

        booking_id = "HTL-889"
        check_in = "2026-07-14"
        check_out = "2026-07-15"
        room_rate = 468.0
        tax_rate = 0.06
        total_price = round(room_rate * (1 + tax_rate), 2)
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
                DEMO_USER_ID,
                "HOTEL-BJ-01",
                "RT-BJ-01-STD",
                "TRIP-5566",
                "张三",
                "13800001111",
                check_in,
                check_out,
                "confirmed",
                room_rate,
                tax_rate,
                total_price,
                "2026-07-10T09:30:00",
                "2026-07-10T09:30:00",
            ),
        )

        for stay_day in _daterange(date.fromisoformat(check_in), date.fromisoformat(check_out)):
            conn.execute(
                """
                UPDATE inventory
                SET available_count = available_count - 1
                WHERE hotel_id = ? AND room_type_id = ? AND stay_date = ?
                """,
                ("HOTEL-BJ-01", "RT-BJ-01-STD", _date_str(stay_day)),
            )

        events = [
            (booking_id, "confirmed", "预订已确认", "2026-07-10T09:30:00"),
            (booking_id, "confirmed", "已关联行程 TRIP-5566", "2026-07-10T09:31:00"),
        ]
        conn.executemany(
            """
            INSERT INTO booking_events (booking_id, status, note, created_at)
            VALUES (?, ?, ?, ?)
            """,
            events,
        )

        conn.commit()
