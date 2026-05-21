"""
packages/context/conversation_store.py

对话历史持久化存储，基于 SQLite。
"""

import json
import os
import sqlite3
import uuid
from typing import Optional

from core.models import Message, Role, ToolCall


class ConversationSQLitesStore:
    """对话历史持久化存储。

    每条消息按 session_id 归档，支持多用户多会话。
    与 ContextAssembler 配合：store 负责完整持久化，assembler 负责裁剪组装。

    Args:
        db_path: SQLite 数据库文件路径
    """

    def __init__(self, db_path: str = "data/memory.db"):
        os.makedirs(os.path.dirname(db_path) or ".", exist_ok=True)
        self.conn = sqlite3.connect(db_path)
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
                created_at   TEXT NOT NULL DEFAULT (strftime('%Y-%m-%d %H:%M:%S', 'now', 'localtime'))
            );
            CREATE INDEX IF NOT EXISTS idx_session_time
                ON conversation_memory(session_id, created_at);
            """
        )
        self.conn.commit()

    def add_message(self, session_id: str, message: Message) -> str:
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
            INSERT INTO conversation_memory (id, session_id, role, content, tool_calls, tool_call_id, name)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                msg_id,
                session_id,
                message.role.value,
                content,
                tool_calls_json,
                message.tool_call_id,
                message.name,
            ),
        )
        self.conn.commit()
        return msg_id

    def get_recent(self, session_id: str, limit: int = 20) -> list[Message]:
        """获取最近 N 条消息（按时间正序返回）。"""
        rows = self.conn.execute(
            """
            SELECT role, content, tool_calls, tool_call_id, name
            FROM conversation_memory
            WHERE session_id = ?
            ORDER BY created_at DESC, rowid DESC
            LIMIT ?
            """,
            (session_id, limit),
        ).fetchall()

        messages = [self._row_to_message(row) for row in reversed(rows)]
        return messages

    def get_all(self, session_id: str) -> list[Message]:
        """获取会话的完整历史。"""
        rows = self.conn.execute(
            """
            SELECT role, content, tool_calls, tool_call_id, name
            FROM conversation_memory
            WHERE session_id = ?
            ORDER BY created_at ASC, rowid ASC
            """,
            (session_id,),
        ).fetchall()

        return [self._row_to_message(row) for row in rows]

    def clear_session(self, session_id: str) -> None:
        """清空指定会话。"""
        self.conn.execute(
            "DELETE FROM conversation_memory WHERE session_id = ?", (session_id,)
        )
        self.conn.commit()

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
    def _row_to_message(row: sqlite3.Row) -> Message:
        """将数据库行转换为 Message 对象。"""
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
