"""对话历史持久化：Postgres。"""

from __future__ import annotations

import uuid
from typing import Any, Optional

from core.models import Message
from memory.store.conversation_codec import encode_message_fields, row_to_message
from memory.store.conversation_protocol import ConversationMessageRecord


def ensure_postgres_database(dsn: str) -> None:
    """若 DSN 指向的库不存在，则连维护库 ``postgres`` 并创建。

    需要当前用户具备 ``CREATEDB``（或超级用户）。表仍由 Store 启动时创建。
    """
    try:
        import psycopg
        from psycopg import sql
        from psycopg.conninfo import conninfo_to_dict, make_conninfo
    except ImportError as exc:  # pragma: no cover
        raise ImportError(
            "使用 memory.conversation_store=postgres 需要安装 psycopg："
            " uv add 'psycopg[binary]'"
        ) from exc

    info = conninfo_to_dict(dsn)
    dbname = (info.get("dbname") or "").strip()
    if not dbname or dbname in ("postgres", "template0", "template1"):
        return

    admin_info = dict(info)
    admin_info["dbname"] = "postgres"
    admin_dsn = make_conninfo(**admin_info)

    try:
        with psycopg.connect(admin_dsn, autocommit=True) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT 1 FROM pg_database WHERE datname = %s",
                    (dbname,),
                )
                if cur.fetchone() is not None:
                    return
                cur.execute(
                    sql.SQL("CREATE DATABASE {}").format(sql.Identifier(dbname))
                )
    except Exception as exc:
        raise RuntimeError(
            f"自动创建 Postgres 库 {dbname!r} 失败（需要 CREATEDB 权限；"
            f"也可手动: CREATE DATABASE {dbname};）: {exc}"
        ) from exc


class ConversationPostgresStore:
    """对话历史持久化（Postgres）。

    排序用 ``seq BIGSERIAL``（等价于 SQLite rowid）。
    首次连接时：库不存在则尝试自动建库，再 ``CREATE TABLE IF NOT EXISTS``。
    """

    def __init__(self, dsn: str):
        try:
            import psycopg
            from psycopg.rows import dict_row
        except ImportError as exc:  # pragma: no cover
            raise ImportError(
                "使用 memory.conversation_store=postgres 需要安装 psycopg："
                " uv add 'psycopg[binary]'"
            ) from exc

        url = (dsn or "").strip()
        if not url:
            raise ValueError("memory.postgres_dsn 不能为空")

        ensure_postgres_database(url)

        self._psycopg = psycopg
        self.conn = psycopg.connect(url, row_factory=dict_row, autocommit=False)
        self._init_db()

    def _init_db(self) -> None:
        with self.conn.cursor() as cur:
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS conversation_memory (
                    id            TEXT PRIMARY KEY,
                    session_id    TEXT NOT NULL,
                    role          TEXT NOT NULL,
                    content       TEXT NOT NULL DEFAULT '',
                    tool_calls    TEXT,
                    tool_call_id  TEXT,
                    name          TEXT,
                    created_at    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                    metadata_json TEXT DEFAULT '{}',
                    source        TEXT DEFAULT 'memory',
                    token_count   INTEGER,
                    turn_index    INTEGER,
                    seq           BIGSERIAL NOT NULL
                )
                """
            )
            cur.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_conversation_session_time
                    ON conversation_memory(session_id, created_at, seq)
                """
            )
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
        msg_id = uuid.uuid4().hex
        content, tool_calls_json, tool_call_id, name, metadata_json = (
            encode_message_fields(message, metadata=metadata)
        )
        with self.conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO conversation_memory
                    (id, session_id, role, content, tool_calls, tool_call_id, name,
                     metadata_json, source, token_count, turn_index)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
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
        with self.conn.cursor() as cur:
            cur.execute(
                """
                SELECT id, role, content, tool_calls, tool_call_id, name, metadata_json
                FROM conversation_memory
                WHERE session_id = %s
                ORDER BY created_at DESC, seq DESC
                LIMIT %s
                """,
                (session_id, limit),
            )
            rows = cur.fetchall()
        return [self._row_to_record(row) for row in reversed(rows)]

    def get_all(self, session_id: str) -> list[Message]:
        return [r.message for r in self.get_all_records(session_id)]

    def get_all_records(self, session_id: str) -> list[ConversationMessageRecord]:
        with self.conn.cursor() as cur:
            cur.execute(
                """
                SELECT id, role, content, tool_calls, tool_call_id, name, metadata_json
                FROM conversation_memory
                WHERE session_id = %s
                ORDER BY created_at ASC, seq ASC
                """,
                (session_id,),
            )
            rows = cur.fetchall()
        return [self._row_to_record(row) for row in rows]

    def get_records_after(
        self,
        session_id: str,
        after_message_id: str | None,
    ) -> list[ConversationMessageRecord]:
        if not after_message_id:
            return self.get_all_records(session_id)

        with self.conn.cursor() as cur:
            cur.execute(
                """
                SELECT created_at, seq
                FROM conversation_memory
                WHERE session_id = %s AND id = %s
                """,
                (session_id, after_message_id),
            )
            anchor = cur.fetchone()
            if anchor is None:
                return self.get_all_records(session_id)

            cur.execute(
                """
                SELECT id, role, content, tool_calls, tool_call_id, name, metadata_json
                FROM conversation_memory
                WHERE session_id = %s
                  AND (
                        created_at > %s
                     OR (created_at = %s AND seq > %s)
                  )
                ORDER BY created_at ASC, seq ASC
                """,
                (
                    session_id,
                    anchor["created_at"],
                    anchor["created_at"],
                    anchor["seq"],
                ),
            )
            rows = cur.fetchall()
        return [self._row_to_record(row) for row in rows]

    def count_user_messages(
        self,
        session_id: str,
        after_message_id: str | None = None,
    ) -> int:
        with self.conn.cursor() as cur:
            if not after_message_id:
                cur.execute(
                    """
                    SELECT COUNT(*) AS cnt
                    FROM conversation_memory
                    WHERE session_id = %s AND role = 'user'
                    """,
                    (session_id,),
                )
                row = cur.fetchone()
                return int(row["cnt"]) if row else 0

            cur.execute(
                """
                SELECT created_at, seq
                FROM conversation_memory
                WHERE session_id = %s AND id = %s
                """,
                (session_id, after_message_id),
            )
            anchor = cur.fetchone()
            if anchor is None:
                cur.execute(
                    """
                    SELECT COUNT(*) AS cnt
                    FROM conversation_memory
                    WHERE session_id = %s AND role = 'user'
                    """,
                    (session_id,),
                )
                row = cur.fetchone()
                return int(row["cnt"]) if row else 0

            cur.execute(
                """
                SELECT COUNT(*) AS cnt
                FROM conversation_memory
                WHERE session_id = %s
                  AND role = 'user'
                  AND (
                        created_at > %s
                     OR (created_at = %s AND seq > %s)
                  )
                """,
                (
                    session_id,
                    anchor["created_at"],
                    anchor["created_at"],
                    anchor["seq"],
                ),
            )
            row = cur.fetchone()
        return int(row["cnt"]) if row else 0

    def get_chat_history(self, session_id: str) -> list[dict[str, str]]:
        with self.conn.cursor() as cur:
            cur.execute(
                """
                SELECT role, content,
                       to_char(created_at, 'YYYY-MM-DD HH24:MI:SS') AS created_at,
                       metadata_json, name, source, tool_calls, tool_call_id
                FROM conversation_memory
                WHERE session_id = %s
                  AND role IN ('user', 'assistant', 'tool')
                ORDER BY created_at ASC, seq ASC
                """,
                (session_id,),
            )
            rows = cur.fetchall()
        return [
            {
                "role": row["role"],
                "content": row["content"] or "",
                "created_at": row["created_at"] or "",
                "metadata_json": row["metadata_json"] or "{}",
                "name": row["name"] or "",
                "source": row["source"] or "",
                "tool_calls_json": row["tool_calls"] or "",
                "tool_call_id": row["tool_call_id"] or "",
            }
            for row in rows
        ]

    def clear_session(self, session_id: str) -> int:
        with self.conn.cursor() as cur:
            cur.execute(
                "DELETE FROM conversation_memory WHERE session_id = %s",
                (session_id,),
            )
            n = cur.rowcount
        self.conn.commit()
        return int(n)

    def list_sessions(self) -> list[dict]:
        with self.conn.cursor() as cur:
            cur.execute(
                """
                SELECT
                    session_id,
                    COUNT(*) AS message_count,
                    to_char(MAX(created_at), 'YYYY-MM-DD HH24:MI:SS') AS last_active
                FROM conversation_memory
                GROUP BY session_id
                ORDER BY MAX(created_at) DESC
                """
            )
            rows = cur.fetchall()
        return [
            {
                "session_id": row["session_id"],
                "message_count": row["message_count"],
                "last_active": row["last_active"],
            }
            for row in rows
        ]

    def count(self, session_id: str) -> int:
        with self.conn.cursor() as cur:
            cur.execute(
                "SELECT COUNT(*) AS cnt FROM conversation_memory WHERE session_id = %s",
                (session_id,),
            )
            row = cur.fetchone()
        return int(row["cnt"]) if row else 0

    @staticmethod
    def _row_to_record(row: dict[str, Any]) -> ConversationMessageRecord:
        return ConversationMessageRecord(
            id=str(row["id"]),
            message=row_to_message(row),
        )

    def close(self) -> None:
        self.conn.close()
