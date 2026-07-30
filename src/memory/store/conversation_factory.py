"""按配置创建会话历史存储（sqlite | postgres）。"""

from __future__ import annotations

from pathlib import Path
from typing import Literal

from memory.store.conversation_postgres_store import ConversationPostgresStore
from memory.store.conversation_protocol import ConversationStore
from memory.store.conversation_sqlite_store import ConversationSQLitesStore

ConversationBackend = Literal["sqlite", "postgres"]


def normalize_conversation_backend(raw: str | None) -> ConversationBackend:
    text = (raw or "sqlite").strip().lower()
    if text in ("sqlite", "postgres"):
        return text  # type: ignore[return-value]
    raise ValueError(
        f"memory.conversation_store 无效: {raw!r}（仅支持 sqlite | postgres）"
    )


def create_conversation_store(
    *,
    backend: str | None = "sqlite",
    db_path: str | None = None,
    postgres_dsn: str | None = None,
) -> ConversationStore:
    """创建会话历史 Store。

    - sqlite：``db_path``（默认 data/memory.db）
    - postgres：``postgres_dsn``（必填）
    """
    kind = normalize_conversation_backend(backend)
    if kind == "postgres":
        dsn = (postgres_dsn or "").strip()
        if not dsn:
            raise ValueError(
                "memory.conversation_store=postgres 时需要 memory.postgres_dsn"
            )
        return ConversationPostgresStore(dsn)

    path = (db_path or "data/memory.db").strip() or "data/memory.db"
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    return ConversationSQLitesStore(path)
