"""Seed demo data for the attraction mock."""

from __future__ import annotations

from datetime import date, timedelta

from .db import connect, init_db

DEMO_USERNAME = "HubloomAttraction"
DEMO_PASSWORD = "HubloomAttraction@2026"
DEMO_TOKEN = "demo-attraction-token"
DEMO_USER_ID = "U-HUBLOOM-ATTRACTION"


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
                "Hubloom 景区演示账号",
                "13800000002",
                "hubloom-attraction@example.com",
                DEMO_TOKEN,
            ),
        )

        attractions = [
            (
                "ATTR-BJ-GUGONG",
                "故宫博物院",
                "北京",
                "东城区景山前街 4 号",
                "010-85007062",
                "明清两代皇家宫殿，世界文化遗产。",
                "08:30-17:00（周一闭馆）",
                "请按预约时段从午门入园，携带身份证件。",
            ),
            (
                "ATTR-BJ-TIANTAN",
                "天坛公园",
                "北京",
                "东城区天坛内东里 7 号",
                "010-67028866",
                "明清皇帝祭天场所，以祈年殿最为著名。",
                "06:00-22:00",
                "建议从东门或南门入园。",
            ),
            (
                "ATTR-BJ-SUMMER",
                "颐和园",
                "北京",
                "海淀区新建宫门路 19 号",
                "010-62881144",
                "清代皇家园林，以昆明湖和万寿山为主体。",
                "06:30-18:00",
                "北宫门或东宫门入园均可。",
            ),
        ]
        conn.executemany(
            """
            INSERT INTO attractions (
                attraction_id, name, city, address, phone, description,
                opening_hours, entry_note
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            attractions,
        )

        policies = [
            (
                "ATTR-BJ-GUGONG",
                "须按预约日期与时段入园，一人一证一票。",
                "迟到超过 30 分钟需联系客服改期，当日 12:00 前未入园视为放弃。",
                "visit_date 前 1 天 20:00 前可免费改期一次。",
                "visit_date 前 1 天 20:00 前取消全额退款。",
            ),
            (
                "ATTR-BJ-TIANTAN",
                "预约票仅限选定日期使用。",
                "可在预约日当天任意时段入园。",
                "visit_date 前 12 小时可免费改期。",
                "visit_date 前 12 小时取消可退款。",
            ),
            (
                "ATTR-BJ-SUMMER",
                "预约票含入园资格，部分园中园另收费。",
                "建议按预约时段入园，高峰可能排队。",
                "visit_date 前 24 小时可改期。",
                "visit_date 前 24 小时可取消。",
            ),
        ]
        conn.executemany(
            """
            INSERT INTO attraction_policies (
                attraction_id, entry_policy, late_entry_policy,
                reschedule_policy, cancellation_policy
            ) VALUES (?, ?, ?, ?, ?)
            """,
            policies,
        )

        ticket_types = [
            (
                "TT-GUGONG-AM",
                "ATTR-BJ-GUGONG",
                "上午场成人票",
                "成人",
                60.0,
                "08:30-12:00 入园时段。",
            ),
            (
                "TT-GUGONG-PM",
                "ATTR-BJ-GUGONG",
                "下午场成人票",
                "成人",
                60.0,
                "12:00-16:30 入园时段。",
            ),
            (
                "TT-TIANTAN-ADULT",
                "ATTR-BJ-TIANTAN",
                "成人联票",
                "成人",
                34.0,
                "含公园及祈年殿等景点。",
            ),
            (
                "TT-SUMMER-ADULT",
                "ATTR-BJ-SUMMER",
                "成人门票",
                "成人",
                30.0,
                "颐和园大门门票。",
            ),
        ]
        conn.executemany(
            """
            INSERT INTO ticket_types (
                ticket_type_id, attraction_id, name, audience, base_price, description
            ) VALUES (?, ?, ?, ?, ?, ?)
            """,
            ticket_types,
        )

        slots_by_type = {
            "TT-GUGONG-AM": ["08:30-12:00"],
            "TT-GUGONG-PM": ["12:00-16:30"],
            "TT-TIANTAN-ADULT": ["09:00-12:00", "12:00-15:00", "15:00-18:00"],
            "TT-SUMMER-ADULT": ["08:00-11:00", "11:00-14:00", "14:00-17:00"],
        }

        start = date(2026, 7, 10)
        end = date(2026, 7, 20)
        inventory_rows = []
        for ticket_type_id, attraction_id, _name, _audience, base_price, _desc in ticket_types:
            for slot in slots_by_type[ticket_type_id]:
                current = start
                while current <= end:
                    inventory_rows.append(
                        (
                            attraction_id,
                            ticket_type_id,
                            current.isoformat(),
                            slot,
                            200,
                            float(base_price),
                        )
                    )
                    current += timedelta(days=1)
        conn.executemany(
            """
            INSERT INTO inventory (
                attraction_id, ticket_type_id, visit_date, entry_slot,
                available_count, price
            ) VALUES (?, ?, ?, ?, ?, ?)
            """,
            inventory_rows,
        )

        ticket_id = "TKT-778"
        visit_date = "2026-07-14"
        entry_slot = "08:30-12:00"
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
                DEMO_USER_ID,
                "ATTR-BJ-GUGONG",
                "TT-GUGONG-AM",
                "TRIP-5566",
                "张三",
                "13800001111",
                visit_date,
                entry_slot,
                "confirmed",
                60.0,
                5.0,
                65.0,
                "2026-07-10T11:00:00",
                "2026-07-10T11:00:00",
            ),
        )

        conn.execute(
            """
            UPDATE inventory
            SET available_count = available_count - 1
            WHERE attraction_id = ? AND ticket_type_id = ? AND visit_date = ? AND entry_slot = ?
            """,
            ("ATTR-BJ-GUGONG", "TT-GUGONG-AM", visit_date, entry_slot),
        )

        events = [
            (ticket_id, "confirmed", "门票预约成功", "2026-07-10T11:00:00"),
            (ticket_id, "confirmed", "已关联行程 TRIP-5566", "2026-07-10T11:01:00"),
        ]
        conn.executemany(
            """
            INSERT INTO ticket_events (ticket_id, status, note, created_at)
            VALUES (?, ?, ?, ?)
            """,
            events,
        )

        conn.commit()
