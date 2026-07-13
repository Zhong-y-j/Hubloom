"""SQLite storage for the travel attraction mock."""

from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from pathlib import Path

DB_DIR = Path(__file__).resolve().parent / "data"
DB_PATH = DB_DIR / "attraction.db"

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

CREATE TABLE IF NOT EXISTS attractions (
    attraction_id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    city TEXT NOT NULL,
    address TEXT NOT NULL,
    phone TEXT NOT NULL,
    description TEXT NOT NULL,
    opening_hours TEXT NOT NULL,
    entry_note TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS attraction_policies (
    attraction_id TEXT PRIMARY KEY,
    entry_policy TEXT NOT NULL,
    late_entry_policy TEXT NOT NULL,
    reschedule_policy TEXT NOT NULL,
    cancellation_policy TEXT NOT NULL,
    FOREIGN KEY (attraction_id) REFERENCES attractions(attraction_id)
);

CREATE TABLE IF NOT EXISTS ticket_types (
    ticket_type_id TEXT PRIMARY KEY,
    attraction_id TEXT NOT NULL,
    name TEXT NOT NULL,
    audience TEXT NOT NULL,
    base_price REAL NOT NULL,
    description TEXT NOT NULL,
    FOREIGN KEY (attraction_id) REFERENCES attractions(attraction_id)
);

CREATE TABLE IF NOT EXISTS inventory (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    attraction_id TEXT NOT NULL,
    ticket_type_id TEXT NOT NULL,
    visit_date TEXT NOT NULL,
    entry_slot TEXT NOT NULL,
    available_count INTEGER NOT NULL,
    price REAL NOT NULL,
    UNIQUE (attraction_id, ticket_type_id, visit_date, entry_slot),
    FOREIGN KEY (attraction_id) REFERENCES attractions(attraction_id),
    FOREIGN KEY (ticket_type_id) REFERENCES ticket_types(ticket_type_id)
);

CREATE TABLE IF NOT EXISTS tickets (
    ticket_id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL,
    attraction_id TEXT NOT NULL,
    ticket_type_id TEXT NOT NULL,
    trip_id TEXT,
    visitor_name TEXT NOT NULL,
    visitor_phone TEXT NOT NULL,
    visit_date TEXT NOT NULL,
    entry_slot TEXT NOT NULL,
    status TEXT NOT NULL,
    ticket_price REAL NOT NULL,
    service_fee REAL NOT NULL DEFAULT 0,
    total_price REAL NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    FOREIGN KEY (user_id) REFERENCES users(user_id),
    FOREIGN KEY (attraction_id) REFERENCES attractions(attraction_id),
    FOREIGN KEY (ticket_type_id) REFERENCES ticket_types(ticket_type_id)
);

CREATE TABLE IF NOT EXISTS ticket_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ticket_id TEXT NOT NULL,
    status TEXT NOT NULL,
    note TEXT NOT NULL,
    created_at TEXT NOT NULL,
    FOREIGN KEY (ticket_id) REFERENCES tickets(ticket_id)
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
