from __future__ import annotations

import json
import sqlite3
import uuid
from typing import Optional

from memory.models import EpisodicItem
from memory.utils import content_hash, now_local_str
from memory.store.base import BaseStore
from memory.store.schema_migrate import ensure_columns


class EpisodicSQLiteStore(BaseStore):
    """Episodic 记忆的 SQLite 存储（episodic_memory 表）。"""

    _EXTRA_COLUMNS = {
        "ref_session_id": "TEXT",
        "content_hash": "TEXT",
        "importance": "INTEGER NOT NULL DEFAULT 0",
    }

    def __init__(self, db_path: str = "data/memory.db"):
        self.conn = sqlite3.connect(db_path)
        self.conn.row_factory = sqlite3.Row
        self._init_db()

    def _init_db(self) -> None:
        self.conn.execute(
            """
            CREATE TABLE IF NOT EXISTS episodic_memory (
                id TEXT PRIMARY KEY,
                content TEXT NOT NULL,
                namespace TEXT NOT NULL,
                source TEXT NOT NULL DEFAULT 'memory',
                metadata_json TEXT DEFAULT '{}',
                created_at TEXT NOT NULL,
                last_accessed_at TEXT NOT NULL,
                access_count INTEGER DEFAULT 0,
                ref_session_id TEXT,
                content_hash TEXT,
                importance INTEGER NOT NULL DEFAULT 0
            )
        """
        )
        ensure_columns(self.conn, "episodic_memory", self._EXTRA_COLUMNS)
        self.conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_episodic_ns_last "
            "ON episodic_memory(namespace, last_accessed_at)"
        )
        self.conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_episodic_ns_created "
            "ON episodic_memory(namespace, created_at)"
        )
        self.conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_episodic_ns_hash "
            "ON episodic_memory(namespace, content_hash)"
        )
        self.conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_episodic_ns_session "
            "ON episodic_memory(namespace, ref_session_id)"
        )
        self.conn.commit()

    @staticmethod
    def _row_to_item(row: sqlite3.Row, *, last_accessed_at: str, access_count: int) -> EpisodicItem:
        keys = row.keys()
        return EpisodicItem(
            id=row["id"],
            content=row["content"],
            namespace=row["namespace"],
            source=row["source"],
            metadata=json.loads(row["metadata_json"]),
            created_at=row["created_at"],
            last_accessed_at=last_accessed_at,
            access_count=access_count,
            ref_session_id=row["ref_session_id"] if "ref_session_id" in keys else None,
            content_hash=row["content_hash"] if "content_hash" in keys else None,
            importance=int(row["importance"]) if "importance" in keys else 0,
        )

    async def ttl_evict(self, namespace: str, threshold_str: str) -> int:
        cur = self.conn.execute(
            "DELETE FROM episodic_memory WHERE namespace = ? AND last_accessed_at < ?",
            (namespace, threshold_str),
        )
        self.conn.commit()
        return cur.rowcount

    async def capacity_evict(self, namespace: str, max_items: int) -> int:
        if max_items <= 0:
            return 0
        row = self.conn.execute(
            "SELECT COUNT(*) FROM episodic_memory WHERE namespace = ?",
            (namespace,),
        ).fetchone()
        count = int(row[0]) if row else 0
        if count <= max_items:
            return 0
        overflow = count - max_items
        rows = self.conn.execute(
            """SELECT id FROM episodic_memory
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
            f"DELETE FROM episodic_memory WHERE namespace = ? AND id IN ({placeholders})",
            (namespace, *ids),
        )
        self.conn.commit()
        return cur.rowcount

    async def add(self, item: EpisodicItem) -> str:
        if not item.id:
            item.id = uuid.uuid4().hex
        if not item.content_hash:
            item.content_hash = content_hash(item.content)

        self.conn.execute(
            """INSERT INTO episodic_memory
               (id, content, namespace, source, metadata_json, created_at, last_accessed_at,
                access_count, ref_session_id, content_hash, importance)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                item.id,
                item.content,
                item.namespace,
                item.source,
                json.dumps(item.metadata, ensure_ascii=False),
                item.created_at,
                item.last_accessed_at,
                item.access_count,
                item.ref_session_id,
                item.content_hash,
                item.importance,
            ),
        )
        self.conn.commit()
        return item.id

    async def search(
        self,
        namespace: str,
        query: str,
        top_k: int = 5,
        filters: Optional[dict] = None,
    ) -> list[EpisodicItem]:
        def _keywords(q: str) -> list[str]:
            q = (q or "").strip()
            if not q:
                return []
            if len(q) <= 6:
                return [q]

            seps = " \t\r\n,，.。;；:：!！?？()（）[]【】{}<>《》\"'“”‘’"
            buf = []
            cur = ""
            for ch in q:
                if ch in seps:
                    if cur:
                        buf.append(cur)
                        cur = ""
                else:
                    cur += ch
            if cur:
                buf.append(cur)

            out: list[str] = []
            for part in buf:
                part = part.strip()
                if not part:
                    continue
                if len(part) <= 6:
                    out.append(part)
                    continue
                out.extend(
                    [part[:2], part[:3], part[:4], part[-2:], part[-3:], part[-4:]]
                )

            uniq: list[str] = []
            seen = set()
            for k in out:
                k = k.strip()
                if len(k) < 2:
                    continue
                if k in seen:
                    continue
                seen.add(k)
                uniq.append(k)
            return uniq[:8]

        if not query.strip():
            rows = self.conn.execute(
                """SELECT * FROM episodic_memory
                   WHERE namespace = ?
                   ORDER BY last_accessed_at DESC, created_at DESC
                   LIMIT ?""",
                (namespace, top_k),
            ).fetchall()
        else:
            keys = _keywords(query)
            if not keys:
                keys = [query]
            where = " OR ".join(["content LIKE ?"] * len(keys))
            params = [namespace, *[f"%{k}%" for k in keys], top_k]
            rows = self.conn.execute(
                f"""SELECT * FROM episodic_memory
                   WHERE namespace = ? AND ({where})
                   ORDER BY created_at DESC
                   LIMIT ?""",
                params,
            ).fetchall()

        rows = self._apply_filters(rows, filters)

        items: list[EpisodicItem] = []
        now = now_local_str()
        for row in rows:
            access_count = int(row["access_count"]) + 1
            item = self._row_to_item(
                row, last_accessed_at=now, access_count=access_count
            )
            items.append(item)
            self.conn.execute(
                "UPDATE episodic_memory SET last_accessed_at = ?, access_count = ? WHERE id = ?",
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
        return out

    async def delete(self, item_id: str, namespace: str) -> bool:
        cursor = self.conn.execute(
            "DELETE FROM episodic_memory WHERE id = ? AND namespace = ?",
            (item_id, namespace),
        )
        self.conn.commit()
        return cursor.rowcount > 0

    async def clear_namespace(self, namespace: str) -> int:
        cursor = self.conn.execute(
            "DELETE FROM episodic_memory WHERE namespace = ?",
            (namespace,),
        )
        self.conn.commit()
        return cursor.rowcount
