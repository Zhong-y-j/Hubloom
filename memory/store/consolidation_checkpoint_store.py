"""批量提炼游标：记录每个 session 已提炼到的最后一条消息。"""

from __future__ import annotations

import os
import sqlite3
from dataclasses import dataclass

from memory.utils import now_local_str


@dataclass(frozen=True)
class ConsolidationCheckpoint:
    session_id: str
    last_message_id: str | None
    turns_consolidated: int
    updated_at: str


class ConsolidationCheckpointStore:
    """SQLite 游标表，与 conversation 共用 ``data/memory.db``。"""

    def __init__(self, db_path: str = "data/memory.db") -> None:
        os.makedirs(os.path.dirname(db_path) or ".", exist_ok=True)
        self.conn = sqlite3.connect(db_path, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self._init_db()

    def _init_db(self) -> None:
        self.conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS memory_consolidation_checkpoint (
                session_id         TEXT PRIMARY KEY,
                last_message_id    TEXT,
                turns_consolidated INTEGER NOT NULL DEFAULT 0,
                updated_at         TEXT NOT NULL DEFAULT (
                    strftime('%Y-%m-%d %H:%M:%S', 'now', 'localtime')
                )
            );
            """
        )
        self.conn.commit()

    def get(self, session_id: str) -> ConsolidationCheckpoint | None:
        row = self.conn.execute(
            """
            SELECT session_id, last_message_id, turns_consolidated, updated_at
            FROM memory_consolidation_checkpoint
            WHERE session_id = ?
            """,
            (session_id,),
        ).fetchone()
        if row is None:
            return None
        return ConsolidationCheckpoint(
            session_id=str(row["session_id"]),
            last_message_id=row["last_message_id"],
            turns_consolidated=int(row["turns_consolidated"]),
            updated_at=str(row["updated_at"]),
        )

    def upsert(
        self,
        session_id: str,
        *,
        last_message_id: str,
        turns_delta: int,
    ) -> ConsolidationCheckpoint:
        existing = self.get(session_id)
        turns = (existing.turns_consolidated if existing else 0) + max(0, turns_delta)
        updated_at = now_local_str()
        self.conn.execute(
            """
            INSERT INTO memory_consolidation_checkpoint
                (session_id, last_message_id, turns_consolidated, updated_at)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(session_id) DO UPDATE SET
                last_message_id = excluded.last_message_id,
                turns_consolidated = excluded.turns_consolidated,
                updated_at = excluded.updated_at
            """,
            (session_id, last_message_id, turns, updated_at),
        )
        self.conn.commit()
        return ConsolidationCheckpoint(
            session_id=session_id,
            last_message_id=last_message_id,
            turns_consolidated=turns,
            updated_at=updated_at,
        )

    def delete(self, session_id: str) -> bool:
        cursor = self.conn.execute(
            "DELETE FROM memory_consolidation_checkpoint WHERE session_id = ?",
            (session_id,),
        )
        self.conn.commit()
        return cursor.rowcount > 0

    def close(self) -> None:
        self.conn.close()
