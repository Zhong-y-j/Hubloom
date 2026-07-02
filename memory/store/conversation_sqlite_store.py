"""
对话历史持久化存储，基于 SQLite。
"""

from __future__ import annotations

import json
import os
import sqlite3
import uuid
from dataclasses import dataclass
from typing import Any, Optional

from core.models import Message, Role, ToolCall
from memory.store.schema_migrate import ensure_columns


@dataclass(frozen=True)
class ConversationMessageRecord:
    """带数据库 id 的会话消息（供批量提炼定位 turn 范围）。"""

    id: str
    message: Message


class ConversationSQLitesStore:
    """对话历史持久化存储。

    每条消息按 session_id 归档，支持多用户多会话。
    与 ContextAssembler 配合：store 负责完整持久化，assembler 负责裁剪组装。
    Args:
        db_path: 数据库文件路径
    Actions:
        add_message: 添加一条消息
        get_recent: 获取最近 N 条消息
        get_all: 获取会话的完整历史
        clear_session: 清空指定会话的全部消息
        list_sessions: 列出所有会话概览
        count: 获取会话消息总数
        close: 关闭数据库连接
    """

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

        tool_calls_json = None
        if message.tool_calls:
            tool_calls_json = json.dumps(
                [
                    {"id": tc.id, "name": tc.name, "arguments": tc.arguments}
                    for tc in message.tool_calls
                ],
                ensure_ascii=False,
            )

        content = (
            message.content
            if isinstance(message.content, str)
            else json.dumps(message.content, ensure_ascii=False)
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
                message.tool_call_id,
                message.name,
                json.dumps(metadata or {}, ensure_ascii=False),
                source,
                token_count,
                turn_index,
            ),
        )
        self.conn.commit()
        return msg_id

    def get_recent(self, session_id: str, limit: int = 20) -> list[Message]:
        """获取最近 N 条消息（按时间正序返回）。"""
        return [r.message for r in self.get_recent_records(session_id, limit)]

    def get_recent_records(
        self, session_id: str, limit: int = 20
    ) -> list[ConversationMessageRecord]:
        """获取最近 N 条消息（含 id，按时间正序）。"""
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
        """获取会话的完整历史。"""
        return [r.message for r in self.get_all_records(session_id)]

    def get_all_records(self, session_id: str) -> list[ConversationMessageRecord]:
        """获取会话完整历史（含 id，按时间正序）。"""
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
        """获取某条消息之后的新消息（不含 checkpoint 本身，按时间正序）。"""
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
        """统计待处理 USER 消息数（用于定量触发）。"""
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
        """获取会话中 user/assistant 消息（含时间戳，按时间正序）。"""
        rows = self.conn.execute(
            """
            SELECT role, content, created_at
            FROM conversation_memory
            WHERE session_id = ? AND role IN ('user', 'assistant')
            ORDER BY created_at ASC, rowid ASC
            """,
            (session_id,),
        ).fetchall()

        return [
            {
                "role": row["role"],
                "content": row["content"] or "",
                "created_at": row["created_at"],
            }
            for row in rows
        ]

    def clear_session(self, session_id: str) -> int:
        """清空指定会话的全部消息，返回删除条数。"""
        cursor = self.conn.execute(
            "DELETE FROM conversation_memory WHERE session_id = ?", (session_id,)
        )
        self.conn.commit()
        return cursor.rowcount

    def list_sessions(self) -> list[dict]:
        """列出所有会话概览。"""
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
        """获取会话消息总数。"""
        row = self.conn.execute(
            "SELECT COUNT(*) as cnt FROM conversation_memory WHERE session_id = ?",
            (session_id,),
        ).fetchone()
        return row["cnt"] if row else 0

    @staticmethod
    def _row_to_record(row: sqlite3.Row) -> ConversationMessageRecord:
        return ConversationMessageRecord(
            id=str(row["id"]),
            message=ConversationSQLitesStore._row_to_message(row),
        )

    @staticmethod
    def _row_to_message(row: sqlite3.Row) -> Message:
        """将数据库行转换为 Message；消息 id 写入 metadata['_id'] 供上层使用。"""
        role_map = {
            "system": Role.SYSTEM,
            "user": Role.USER,
            "assistant": Role.ASSISTANT,
            "tool": Role.TOOL,
        }
        role = role_map.get(row["role"], Role.USER)

        tool_calls = None
        if row["tool_calls"]:
            raw = json.loads(row["tool_calls"])
            tool_calls = [
                ToolCall(id=tc["id"], name=tc["name"], arguments=tc["arguments"])
                for tc in raw
            ]

        return Message(
            role=role,
            content=row["content"],
            tool_calls=tool_calls,
            tool_call_id=row["tool_call_id"],
            name=row["name"],
        )

    def close(self) -> None:
        self.conn.close()


if __name__ == "__main__":
    store = ConversationSQLitesStore()
    store.add_message("test", Message(role=Role.USER, content="Hello, world!"))
    print(store.get_recent("test"))
