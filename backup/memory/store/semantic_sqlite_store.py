from __future__ import annotations

import json
import math
import sqlite3
import uuid
from typing import Optional

from memory.models import SemanticItem
from memory.utils import content_hash, now_local_str
from memory.store.base import BaseStore
from memory.store.schema_migrate import ensure_columns


class SemanticSQLiteStore(BaseStore):
    """Semantic 记忆的 SQLite 存储（semantic_memory 表）。"""

    _EXTRA_COLUMNS = {
        "ref_session_id": "TEXT",
        "content_hash": "TEXT",
        "embedding_model": "TEXT",
        "embedding_dim": "INTEGER",
        "importance": "INTEGER NOT NULL DEFAULT 0",
    }

    def __init__(self, db_path: str = "data/memory.db"):
        self.conn = sqlite3.connect(db_path)
        self.conn.row_factory = sqlite3.Row
        self._init_db()

    def _init_db(self) -> None:
        self.conn.execute(
            """
            CREATE TABLE IF NOT EXISTS semantic_memory (
                id TEXT PRIMARY KEY,
                content TEXT NOT NULL,
                namespace TEXT NOT NULL,
                source TEXT NOT NULL DEFAULT 'memory',
                metadata_json TEXT DEFAULT '{}',
                embedding_json TEXT NOT NULL,
                created_at TEXT NOT NULL,
                last_accessed_at TEXT NOT NULL,
                access_count INTEGER DEFAULT 0,
                ref_session_id TEXT,
                content_hash TEXT,
                embedding_model TEXT,
                embedding_dim INTEGER,
                importance INTEGER NOT NULL DEFAULT 0
            )
        """
        )
        ensure_columns(self.conn, "semantic_memory", self._EXTRA_COLUMNS)
        self.conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_semantic_ns_last "
            "ON semantic_memory(namespace, last_accessed_at)"
        )
        self.conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_semantic_ns_created "
            "ON semantic_memory(namespace, created_at)"
        )
        self.conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_semantic_ns_hash "
            "ON semantic_memory(namespace, content_hash)"
        )
        self.conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_semantic_ns_session "
            "ON semantic_memory(namespace, ref_session_id)"
        )
        self.conn.commit()

    @staticmethod
    def _row_to_item(row: sqlite3.Row, *, last_accessed_at: str, access_count: int) -> SemanticItem:
        keys = row.keys()
        return SemanticItem(
            id=row["id"],
            content=row["content"],
            namespace=row["namespace"],
            source=row["source"],
            metadata=json.loads(row["metadata_json"]),
            created_at=row["created_at"],
            last_accessed_at=last_accessed_at,
            access_count=access_count,
            embedding=json.loads(row["embedding_json"]),
            ref_session_id=row["ref_session_id"] if "ref_session_id" in keys else None,
            content_hash=row["content_hash"] if "content_hash" in keys else None,
            embedding_model=row["embedding_model"] if "embedding_model" in keys else None,
            embedding_dim=(
                int(row["embedding_dim"])
                if "embedding_dim" in keys and row["embedding_dim"] is not None
                else None
            ),
            importance=int(row["importance"]) if "importance" in keys else 0,
        )

    async def ttl_evict(self, namespace: str, threshold_str: str) -> int:
        cur = self.conn.execute(
            "DELETE FROM semantic_memory WHERE namespace = ? AND last_accessed_at < ?",
            (namespace, threshold_str),
        )
        self.conn.commit()
        return cur.rowcount

    async def capacity_evict(self, namespace: str, max_items: int) -> int:
        if max_items <= 0:
            return 0
        row = self.conn.execute(
            "SELECT COUNT(*) FROM semantic_memory WHERE namespace = ?",
            (namespace,),
        ).fetchone()
        count = int(row[0]) if row else 0
        if count <= max_items:
            return 0
        overflow = count - max_items
        rows = self.conn.execute(
            """SELECT id FROM semantic_memory
               WHERE namespace = ?
               ORDER BY importance ASC, last_accessed_at ASC, access_count ASC, created_at ASC
               LIMIT ?""",
            (namespace, overflow),
        ).fetchall()
        ids = [r[0] for r in rows]
        if not ids:
            return 0
        placeholders = ",".join("?" * len(ids))
        cur = self.conn.execute(
            f"DELETE FROM semantic_memory WHERE namespace = ? AND id IN ({placeholders})",
            (namespace, *ids),
        )
        self.conn.commit()
        return cur.rowcount

    async def add(self, item: SemanticItem) -> str:
        if not item.id:
            item.id = uuid.uuid4().hex
        if not item.content_hash:
            item.content_hash = content_hash(item.content)
        if item.embedding_dim is None and item.embedding:
            item.embedding_dim = len(item.embedding)

        self.conn.execute(
            """INSERT INTO semantic_memory
               (id, content, namespace, source, metadata_json, embedding_json, created_at,
                last_accessed_at, access_count, ref_session_id, content_hash,
                embedding_model, embedding_dim, importance)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                item.id,
                item.content,
                item.namespace,
                item.source,
                json.dumps(item.metadata, ensure_ascii=False),
                json.dumps(item.embedding),
                item.created_at,
                item.last_accessed_at,
                item.access_count,
                item.ref_session_id,
                item.content_hash,
                item.embedding_model,
                item.embedding_dim,
                item.importance,
            ),
        )
        self.conn.commit()
        return item.id

    async def search(
        self,
        *,
        namespace: str,
        query_embedding: list[float],
        top_k: int = 5,
        filters: Optional[dict] = None,
    ) -> list[SemanticItem]:
        candidate_limit = 800
        rows = self.conn.execute(
            """SELECT * FROM semantic_memory
               WHERE namespace = ?
               ORDER BY created_at DESC
               LIMIT ?""",
            (namespace, candidate_limit),
        ).fetchall()

        rows = self._apply_filters(rows, filters)

        def _cos(a: list[float], b: list[float]) -> float:
            dot = 0.0
            na = 0.0
            nb = 0.0
            for x, y in zip(a, b):
                dot += x * y
                na += x * x
                nb += y * y
            if na <= 0.0 or nb <= 0.0:
                return -1.0
            return dot / (math.sqrt(na) * math.sqrt(nb))

        scored: list[tuple[float, sqlite3.Row]] = []
        for r in rows:
            try:
                emb = json.loads(r["embedding_json"])
                if not isinstance(emb, list) or not emb:
                    continue
                score = _cos(query_embedding, emb)
                scored.append((score, r))
            except Exception:
                continue

        scored.sort(key=lambda x: x[0], reverse=True)
        selected = scored[:top_k]

        items: list[SemanticItem] = []
        now = now_local_str()
        for _score, row in selected:
            access_count = int(row["access_count"]) + 1
            item = self._row_to_item(
                row, last_accessed_at=now, access_count=access_count
            )
            items.append(item)
            self.conn.execute(
                "UPDATE semantic_memory SET last_accessed_at = ?, access_count = ? WHERE id = ?",
                (now, access_count, item.id),
            )
        if items:
            self.conn.commit()
        return items

    @staticmethod
    def _apply_filters(rows: list[sqlite3.Row], filters: Optional[dict]) -> list[sqlite3.Row]:
        if not filters:
            return rows
        out = rows
        if "source" in filters:
            out = [r for r in out if r["source"] == filters["source"]]
        if "ref_session_id" in filters:
            out = [
                r
                for r in out
                if "ref_session_id" in r.keys()
                and r["ref_session_id"] == filters["ref_session_id"]
            ]
        if "embedding_model" in filters:
            out = [
                r
                for r in out
                if "embedding_model" in r.keys()
                and r["embedding_model"] == filters["embedding_model"]
            ]
        return out

    async def delete(self, item_id: str, namespace: str) -> bool:
        cursor = self.conn.execute(
            "DELETE FROM semantic_memory WHERE id = ? AND namespace = ?",
            (item_id, namespace),
        )
        self.conn.commit()
        return cursor.rowcount > 0

    async def clear_namespace(self, namespace: str) -> int:
        cursor = self.conn.execute(
            "DELETE FROM semantic_memory WHERE namespace = ?",
            (namespace,),
        )
        self.conn.commit()
        return cursor.rowcount
