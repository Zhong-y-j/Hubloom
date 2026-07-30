"""会话历史 Store 工厂：sqlite | postgres 配置选择。"""

from __future__ import annotations

from pathlib import Path

import psycopg
import pytest

from memory.store import (
    ConversationPostgresStore,
    ConversationSQLitesStore,
    create_conversation_store,
    ensure_postgres_database,
    normalize_conversation_backend,
)


def test_normalize_backend_default_and_aliases() -> None:
    assert normalize_conversation_backend(None) == "sqlite"
    assert normalize_conversation_backend(" SQLite ") == "sqlite"
    assert normalize_conversation_backend("postgres") == "postgres"


def test_normalize_backend_rejects_unknown() -> None:
    with pytest.raises(ValueError, match="conversation_store"):
        normalize_conversation_backend("mysql")


def test_create_sqlite_store(tmp_path: Path) -> None:
    db = tmp_path / "conv.db"
    store = create_conversation_store(backend="sqlite", db_path=str(db))
    try:
        assert isinstance(store, ConversationSQLitesStore)
        assert db.exists()
    finally:
        store.close()


def test_create_postgres_requires_dsn() -> None:
    with pytest.raises(ValueError, match="postgres_dsn"):
        create_conversation_store(backend="postgres", postgres_dsn=None)


def test_create_postgres_store_type_without_connect(monkeypatch: pytest.MonkeyPatch) -> None:
    """不连真库：只验证 factory 走到 Postgres 类（构造里会 connect，故 mock）。"""

    class _FakeStore:
        def __init__(self, dsn: str) -> None:
            self.dsn = dsn

    monkeypatch.setattr(
        "memory.store.conversation_factory.ConversationPostgresStore",
        _FakeStore,
    )
    store = create_conversation_store(
        backend="postgres",
        postgres_dsn="postgresql://u:p@127.0.0.1:5432/hubloom",
    )
    assert isinstance(store, _FakeStore)
    assert store.dsn.startswith("postgresql://")


def test_ensure_postgres_database_skips_system_db(monkeypatch: pytest.MonkeyPatch) -> None:
    def _boom(*_a: object, **_k: object) -> None:
        raise AssertionError("system db 不应去连维护库建库")

    monkeypatch.setattr(psycopg, "connect", _boom)
    ensure_postgres_database("postgresql://u:p@127.0.0.1:5432/postgres")
    ensure_postgres_database("postgresql://u:p@127.0.0.1:5432/template1")


def test_ensure_postgres_database_creates_when_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    executed: list[str] = []

    class _Cur:
        def __enter__(self) -> "_Cur":
            return self

        def __exit__(self, *_a: object) -> None:
            return None

        def execute(self, query: object, params: object = None) -> None:
            executed.append(str(query))

        def fetchone(self) -> None:
            return None

    class _Conn:
        def __enter__(self) -> "_Conn":
            return self

        def __exit__(self, *_a: object) -> None:
            return None

        def cursor(self) -> _Cur:
            return _Cur()

    def _connect(dsn: str, **_kwargs: object) -> _Conn:
        assert "dbname=postgres" in dsn.replace(" ", "")
        return _Conn()

    monkeypatch.setattr(psycopg, "connect", _connect)
    ensure_postgres_database("postgresql://u:p@127.0.0.1:5432/hubloom")
    assert any("pg_database" in q for q in executed)
    assert any("CREATE DATABASE" in q for q in executed)


def test_ensure_postgres_database_noop_when_exists(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    executed: list[str] = []

    class _Cur:
        def __enter__(self) -> "_Cur":
            return self

        def __exit__(self, *_a: object) -> None:
            return None

        def execute(self, query: object, params: object = None) -> None:
            executed.append(str(query))

        def fetchone(self) -> tuple[int]:
            return (1,)

    class _Conn:
        def __enter__(self) -> "_Conn":
            return self

        def __exit__(self, *_a: object) -> None:
            return None

        def cursor(self) -> _Cur:
            return _Cur()

    monkeypatch.setattr(psycopg, "connect", lambda *_a, **_k: _Conn())
    ensure_postgres_database("postgresql://u:p@127.0.0.1:5432/hubloom")
    assert any("pg_database" in q for q in executed)
    assert not any("CREATE DATABASE" in q for q in executed)


def test_postgres_store_import_message() -> None:
    assert ConversationPostgresStore.__name__ == "ConversationPostgresStore"
