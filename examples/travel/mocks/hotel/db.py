"""SQLite storage for the travel hotel mock."""

from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from pathlib import Path

DB_DIR = Path(__file__).resolve().parent / "data"
DB_PATH = DB_DIR / "hotel.db"

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    user_id TEXT PRIMARY KEY,
    username TEXT NOT NULL UNIQUE,
    password TEXT NOT NULL,
    display_name TEXT NOT NULL,
    phone TEXT,
    email TEXT,
    token TEXT NOT NULL UNIQUE
);

CREATE TABLE IF NOT EXISTS hotels (
    hotel_id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    city TEXT NOT NULL,
    address TEXT NOT NULL,
    phone TEXT NOT NULL,
    description TEXT NOT NULL,
    check_in_time TEXT NOT NULL DEFAULT '14:00',
    check_out_time TEXT NOT NULL DEFAULT '12:00',
    late_arrival_hold_until TEXT NOT NULL DEFAULT '20:00',
    cancellation_policy TEXT NOT NULL,
    check_in_note TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS hotel_facilities (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    hotel_id TEXT NOT NULL,
    name TEXT NOT NULL,
    FOREIGN KEY (hotel_id) REFERENCES hotels(hotel_id)
);

CREATE TABLE IF NOT EXISTS hotel_reviews (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    hotel_id TEXT NOT NULL,
    author TEXT NOT NULL,
    rating REAL NOT NULL,
    comment TEXT NOT NULL,
    FOREIGN KEY (hotel_id) REFERENCES hotels(hotel_id)
);

CREATE TABLE IF NOT EXISTS room_types (
    room_type_id TEXT PRIMARY KEY,
    hotel_id TEXT NOT NULL,
    name TEXT NOT NULL,
    bed_type TEXT NOT NULL,
    area_sqm REAL NOT NULL,
    max_guests INTEGER NOT NULL,
    base_price REAL NOT NULL,
    description TEXT NOT NULL,
    FOREIGN KEY (hotel_id) REFERENCES hotels(hotel_id)
);

CREATE TABLE IF NOT EXISTS inventory (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    hotel_id TEXT NOT NULL,
    room_type_id TEXT NOT NULL,
    stay_date TEXT NOT NULL,
    available_count INTEGER NOT NULL,
    price REAL NOT NULL,
    UNIQUE (hotel_id, room_type_id, stay_date),
    FOREIGN KEY (hotel_id) REFERENCES hotels(hotel_id),
    FOREIGN KEY (room_type_id) REFERENCES room_types(room_type_id)
);

CREATE TABLE IF NOT EXISTS bookings (
    booking_id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL,
    hotel_id TEXT NOT NULL,
    room_type_id TEXT NOT NULL,
    trip_id TEXT,
    guest_name TEXT NOT NULL,
    guest_phone TEXT NOT NULL,
    check_in TEXT NOT NULL,
    check_out TEXT NOT NULL,
    status TEXT NOT NULL,
    room_rate REAL NOT NULL,
    tax_rate REAL NOT NULL DEFAULT 0.06,
    total_price REAL NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    FOREIGN KEY (user_id) REFERENCES users(user_id),
    FOREIGN KEY (hotel_id) REFERENCES hotels(hotel_id),
    FOREIGN KEY (room_type_id) REFERENCES room_types(room_type_id)
);

CREATE TABLE IF NOT EXISTS booking_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    booking_id TEXT NOT NULL,
    status TEXT NOT NULL,
    note TEXT NOT NULL,
    created_at TEXT NOT NULL,
    FOREIGN KEY (booking_id) REFERENCES bookings(booking_id)
);
"""


def init_db() -> None:
    DB_DIR.mkdir(parents=True, exist_ok=True)
    with connect() as conn:
        conn.executescript(SCHEMA)
        conn.commit()


@contextmanager
def connect():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
    finally:
        conn.close()
