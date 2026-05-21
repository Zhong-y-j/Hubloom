from __future__ import annotations

import json
import math
import sqlite3
import uuid
from typing import Optional

from memory.models import SemanticItem
from memory.utils import now_local_str
from memory.store.base import BaseStore


class SemanticSQLiteStore(BaseStore):
    """Semantic 记忆的 SQLite 存储（semantic_memory 表）。

    存储数据字段:
    - id: 记忆 ID
    - content: 记忆内容
    - namespace: 命名空间
    - source: 记忆来源
    - metadata_json: 记忆元数据
    - embedding_json: 记忆嵌入
    - created_at: 记忆创建时间
    - last_accessed_at: 记忆最后一次访问时间
    - access_count: 记忆访问次数
    """

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
                access_count INTEGER DEFAULT 0
            )
        """
        )
        self.conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_semantic_ns_last "
            "ON semantic_memory(namespace, last_accessed_at)"
        )
        self.conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_semantic_ns_created "
            "ON semantic_memory(namespace, created_at)"
        )
        self.conn.commit()

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
               ORDER BY last_accessed_at ASC, access_count ASC, created_at ASC
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

        self.conn.execute(
            """INSERT INTO semantic_memory
               (id, content, namespace, source, metadata_json, embedding_json, created_at, last_accessed_at, access_count)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                item.id,
                item.content,
                item.namespace,
                item.source,
                json.dumps(item.metadata),
                json.dumps(item.embedding),
                item.created_at,
                item.last_accessed_at,
                item.access_count,
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

        if filters and "source" in filters:
            rows = [r for r in rows if r["source"] == filters["source"]]

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
            item = SemanticItem(
                id=row["id"],
                content=row["content"],
                namespace=row["namespace"],
                source=row["source"],
                metadata=json.loads(row["metadata_json"]),
                created_at=row["created_at"],
                last_accessed_at=now,
                access_count=row["access_count"] + 1,
                embedding=json.loads(row["embedding_json"]),
            )
            items.append(item)
            self.conn.execute(
                "UPDATE semantic_memory SET last_accessed_at = ?, access_count = ? WHERE id = ?",
                (now, item.access_count, item.id),
            )
        if items:
            self.conn.commit()
        return items

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
