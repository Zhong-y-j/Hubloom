"""会话历史存储协议（SQLite / Postgres 共用）。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Optional, Protocol

from core.models import Message


@dataclass(frozen=True)
class ConversationMessageRecord:
    """带数据库 id 的会话消息（供批量提炼定位 turn 范围）。"""

    id: str
    message: Message


class ConversationStore(Protocol):
    """对话历史持久化端口。"""

    def add_message(
        self,
        session_id: str,
        message: Message,
        *,
        source: str = "memory",
        metadata: Optional[dict[str, Any]] = None,
        token_count: int | None = None,
        turn_index: int | None = None,
    ) -> str: ...

    def get_recent(self, session_id: str, limit: int = 20) -> list[Message]: ...

    def get_recent_records(
        self, session_id: str, limit: int = 20
    ) -> list[ConversationMessageRecord]: ...

    def get_all(self, session_id: str) -> list[Message]: ...

    def get_all_records(
        self, session_id: str
    ) -> list[ConversationMessageRecord]: ...

    def get_records_after(
        self,
        session_id: str,
        after_message_id: str | None,
    ) -> list[ConversationMessageRecord]: ...

    def count_user_messages(
        self,
        session_id: str,
        after_message_id: str | None = None,
    ) -> int: ...

    def get_chat_history(self, session_id: str) -> list[dict[str, str]]: ...

    def clear_session(self, session_id: str) -> int: ...

    def list_sessions(self) -> list[dict]: ...

    def count(self, session_id: str) -> int: ...

    def close(self) -> None: ...
