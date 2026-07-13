"""SQLite storage for the travel transport mock."""

from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from pathlib import Path

DB_DIR = Path(__file__).resolve().parent / "data"
DB_PATH = DB_DIR / "transport.db"

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

CREATE TABLE IF NOT EXISTS stations (
    station_id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    city TEXT NOT NULL,
    code TEXT NOT NULL UNIQUE
);

CREATE TABLE IF NOT EXISTS trains (
    train_no TEXT PRIMARY KEY,
    train_type TEXT NOT NULL,
    from_station_id TEXT NOT NULL,
    to_station_id TEXT NOT NULL,
    depart_time TEXT NOT NULL,
    arrive_time TEXT NOT NULL,
    duration_minutes INTEGER NOT NULL,
    description TEXT NOT NULL,
    FOREIGN KEY (from_station_id) REFERENCES stations(station_id),
    FOREIGN KEY (to_station_id) REFERENCES stations(station_id)
);

CREATE TABLE IF NOT EXISTS train_stops (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    train_no TEXT NOT NULL,
    station_id TEXT NOT NULL,
    stop_order INTEGER NOT NULL,
    arrive_time TEXT,
    depart_time TEXT,
    FOREIGN KEY (train_no) REFERENCES trains(train_no),
    FOREIGN KEY (station_id) REFERENCES stations(station_id)
);

CREATE TABLE IF NOT EXISTS train_status (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    train_no TEXT NOT NULL,
    travel_date TEXT NOT NULL,
    status TEXT NOT NULL,
    planned_departure TEXT NOT NULL,
    planned_arrival TEXT NOT NULL,
    actual_departure TEXT,
    estimated_arrival TEXT,
    delay_minutes INTEGER NOT NULL DEFAULT 0,
    reason TEXT,
    UNIQUE (train_no, travel_date),
    FOREIGN KEY (train_no) REFERENCES trains(train_no)
);

CREATE TABLE IF NOT EXISTS seat_types (
    seat_type_id TEXT PRIMARY KEY,
    train_no TEXT NOT NULL,
    name TEXT NOT NULL,
    price REAL NOT NULL,
    description TEXT NOT NULL,
    FOREIGN KEY (train_no) REFERENCES trains(train_no)
);

CREATE TABLE IF NOT EXISTS inventory (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    train_no TEXT NOT NULL,
    travel_date TEXT NOT NULL,
    seat_type_id TEXT NOT NULL,
    available_count INTEGER NOT NULL,
    price REAL NOT NULL,
    UNIQUE (train_no, travel_date, seat_type_id),
    FOREIGN KEY (train_no) REFERENCES trains(train_no),
    FOREIGN KEY (seat_type_id) REFERENCES seat_types(seat_type_id)
);

CREATE TABLE IF NOT EXISTS trips (
    trip_id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL,
    train_no TEXT NOT NULL,
    travel_date TEXT NOT NULL,
    seat_type_id TEXT NOT NULL,
    passenger_name TEXT NOT NULL,
    passenger_phone TEXT NOT NULL,
    from_station_id TEXT NOT NULL,
    to_station_id TEXT NOT NULL,
    status TEXT NOT NULL,
    ticket_price REAL NOT NULL,
    service_fee REAL NOT NULL DEFAULT 0,
    total_price REAL NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    FOREIGN KEY (user_id) REFERENCES users(user_id),
    FOREIGN KEY (train_no) REFERENCES trains(train_no),
    FOREIGN KEY (seat_type_id) REFERENCES seat_types(seat_type_id)
);

CREATE TABLE IF NOT EXISTS trip_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    trip_id TEXT NOT NULL,
    status TEXT NOT NULL,
    note TEXT NOT NULL,
    created_at TEXT NOT NULL,
    FOREIGN KEY (trip_id) REFERENCES trips(trip_id)
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
