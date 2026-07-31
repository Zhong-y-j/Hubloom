"""
对话历史持久化存储，基于 SQLite。
"""

from __future__ import annotations

import os
import sqlite3
import uuid
from typing import Any, Optional

from core.models import Message
from memory.store.conversation_codec import (
    encode_message_fields,
    row_to_message,
)
from memory.store.conversation_protocol import ConversationMessageRecord
from memory.store.schema_migrate import ensure_columns

# 兼容旧导入路径
__all__ = ["ConversationMessageRecord", "ConversationSQLitesStore"]


class ConversationSQLitesStore:
    """对话历史持久化存储（SQLite）。"""

    _EXTRA_COLUMNS = {
        "metadata_json": "TEXT DEFAULT '{}'",
        "source": "TEXT DEFAULT 'memory'",
        "token_count": "INTEGER",
        "turn_index": "INTEGER",
    }

    def __init__(self, db_path: str = "data/memory.db"):
        os.makedirs(os.path.dirname(db_path) or ".", exist_ok=True)
        self.conn = sqlite3.connect(db_path, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self._init_db()

    def _init_db(self) -> None:
        self.conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS conversation_memory (
                id           TEXT PRIMARY KEY,
                session_id   TEXT NOT NULL,
                role         TEXT NOT NULL,
                content      TEXT NOT NULL DEFAULT '',
                tool_calls   TEXT,
                tool_call_id TEXT,
                name         TEXT,
                created_at   TEXT NOT NULL DEFAULT (strftime('%Y-%m-%d %H:%M:%S', 'now', 'localtime')),
                metadata_json TEXT DEFAULT '{}',
                source       TEXT DEFAULT 'memory',
                token_count  INTEGER,
                turn_index   INTEGER
            );
            CREATE INDEX IF NOT EXISTS idx_session_time
                ON conversation_memory(session_id, created_at);
            """
        )
        ensure_columns(self.conn, "conversation_memory", self._EXTRA_COLUMNS)
        self.conn.commit()

    def add_message(
        self,
        session_id: str,
        message: Message,
        *,
        source: str = "memory",
        metadata: Optional[dict[str, Any]] = None,
        token_count: int | None = None,
        turn_index: int | None = None,
    ) -> str:
        """持久化一条消息，返回生成的消息 ID。"""
        msg_id = uuid.uuid4().hex
        content, tool_calls_json, tool_call_id, name, metadata_json = (
            encode_message_fields(message, metadata=metadata)
        )

        self.conn.execute(
            """
            INSERT INTO conversation_memory
                (id, session_id, role, content, tool_calls, tool_call_id, name,
                 metadata_json, source, token_count, turn_index)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                msg_id,
                session_id,
                message.role.value,
                content,
                tool_calls_json,
                tool_call_id,
                name,
                metadata_json,
                source,
                token_count,
                turn_index,
            ),
        )
        self.conn.commit()
        return msg_id

    def get_recent(self, session_id: str, limit: int = 20) -> list[Message]:
        return [r.message for r in self.get_recent_records(session_id, limit)]

    def get_recent_records(
        self, session_id: str, limit: int = 20
    ) -> list[ConversationMessageRecord]:
        rows = self.conn.execute(
            """
            SELECT id, role, content, tool_calls, tool_call_id, name, metadata_json
            FROM conversation_memory
            WHERE session_id = ?
            ORDER BY created_at DESC, rowid DESC
            LIMIT ?
            """,
            (session_id, limit),
        ).fetchall()
        return [self._row_to_record(row) for row in reversed(rows)]

    def get_all(self, session_id: str) -> list[Message]:
        return [r.message for r in self.get_all_records(session_id)]

    def get_all_records(self, session_id: str) -> list[ConversationMessageRecord]:
        rows = self.conn.execute(
            """
            SELECT id, role, content, tool_calls, tool_call_id, name, metadata_json
            FROM conversation_memory
            WHERE session_id = ?
            ORDER BY created_at ASC, rowid ASC
            """,
            (session_id,),
        ).fetchall()
        return [self._row_to_record(row) for row in rows]

    def get_records_after(
        self,
        session_id: str,
        after_message_id: str | None,
    ) -> list[ConversationMessageRecord]:
        if not after_message_id:
            return self.get_all_records(session_id)

        anchor = self.conn.execute(
            """
            SELECT created_at, rowid
            FROM conversation_memory
            WHERE session_id = ? AND id = ?
            """,
            (session_id, after_message_id),
        ).fetchone()
        if anchor is None:
            return self.get_all_records(session_id)

        rows = self.conn.execute(
            """
            SELECT id, role, content, tool_calls, tool_call_id, name, metadata_json
            FROM conversation_memory
            WHERE session_id = ?
              AND (
                    created_at > ?
                 OR (created_at = ? AND rowid > ?)
              )
            ORDER BY created_at ASC, rowid ASC
            """,
            (
                session_id,
                anchor["created_at"],
                anchor["created_at"],
                anchor["rowid"],
            ),
        ).fetchall()
        return [self._row_to_record(row) for row in rows]

    def count_user_messages(
        self,
        session_id: str,
        after_message_id: str | None = None,
    ) -> int:
        if not after_message_id:
            row = self.conn.execute(
                """
                SELECT COUNT(*) AS cnt
                FROM conversation_memory
                WHERE session_id = ? AND role = 'user'
                """,
                (session_id,),
            ).fetchone()
            return int(row["cnt"]) if row else 0

        anchor = self.conn.execute(
            """
            SELECT created_at, rowid
            FROM conversation_memory
            WHERE session_id = ? AND id = ?
            """,
            (session_id, after_message_id),
        ).fetchone()
        if anchor is None:
            row = self.conn.execute(
                """
                SELECT COUNT(*) AS cnt
                FROM conversation_memory
                WHERE session_id = ? AND role = 'user'
                """,
                (session_id,),
            ).fetchone()
            return int(row["cnt"]) if row else 0

        row = self.conn.execute(
            """
            SELECT COUNT(*) AS cnt
            FROM conversation_memory
            WHERE session_id = ?
              AND role = 'user'
              AND (
                    created_at > ?
                 OR (created_at = ? AND rowid > ?)
              )
            """,
            (
                session_id,
                anchor["created_at"],
                anchor["created_at"],
                anchor["rowid"],
            ),
        ).fetchone()
        return int(row["cnt"]) if row else 0

    def get_chat_history(self, session_id: str) -> list[dict[str, str]]:
        rows = self.conn.execute(
            """
            SELECT role, content, created_at, metadata_json, name, source,
                   tool_calls, tool_call_id
            FROM conversation_memory
            WHERE session_id = ?
              AND role IN ('user', 'assistant', 'tool')
            ORDER BY created_at ASC, rowid ASC
            """,
            (session_id,),
        ).fetchall()

        return [
            {
                "role": row["role"],
                "content": row["content"] or "",
                "created_at": row["created_at"],
                "metadata_json": row["metadata_json"] or "{}",
                "name": row["name"] or "",
                "source": row["source"] or "",
                "tool_calls_json": row["tool_calls"] or "",
                "tool_call_id": row["tool_call_id"] or "",
            }
            for row in rows
        ]

    def clear_session(self, session_id: str) -> int:
        cursor = self.conn.execute(
            "DELETE FROM conversation_memory WHERE session_id = ?", (session_id,)
        )
        self.conn.commit()
        return cursor.rowcount

    def list_sessions(self) -> list[dict]:
        rows = self.conn.execute(
            """
            SELECT
                session_id,
                COUNT(*) as message_count,
                MAX(created_at) as last_active
            FROM conversation_memory
            GROUP BY session_id
            ORDER BY last_active DESC
            """
        ).fetchall()

        return [
            {
                "session_id": row["session_id"],
                "message_count": row["message_count"],
                "last_active": row["last_active"],
            }
            for row in rows
        ]

    def count(self, session_id: str) -> int:
        row = self.conn.execute(
            "SELECT COUNT(*) as cnt FROM conversation_memory WHERE session_id = ?",
            (session_id,),
        ).fetchone()
        return row["cnt"] if row else 0

    @staticmethod
    def _row_to_record(row: sqlite3.Row) -> ConversationMessageRecord:
        return ConversationMessageRecord(
            id=str(row["id"]),
            message=row_to_message(row),
        )

    def close(self) -> None:
        self.conn.close()


if __name__ == "__main__":
    from core.models import Role

    store = ConversationSQLitesStore()
    store.add_message("test", Message(role=Role.USER, content="Hello, world!"))
    print(store.get_recent("test"))
