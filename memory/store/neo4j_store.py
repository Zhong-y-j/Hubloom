"""Neo4j 联想记忆存储：Entity + RELATES_TO + MemoryRef（HAS_MEMORY）。"""

from __future__ import annotations

import json
import os
import socket
import subprocess
import uuid
from pathlib import Path
from typing import Any, Optional
from urllib.parse import urlparse

from dotenv import load_dotenv
from neo4j import AsyncGraphDatabase, AsyncDriver

from memory.models import (
    AssociativeRecallResult,
    GraphEntity,
    GraphMemoryRef,
    GraphRelation,
)
from memory.types import EntityType, LongTermMemoryType, MemorySource
from memory.utils import now_local_str

load_dotenv()

_SCHEMA_FILE = Path(__file__).with_name("neo4j_schema.cypher")


def _json_dumps(obj: dict[str, Any]) -> str:
    return json.dumps(obj or {}, ensure_ascii=False)


def _uri_hostname(uri: str) -> str:
    return urlparse(uri).hostname or ""


def _system_dns_resolves(host: str, port: int = 7687) -> bool:
    try:
        socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
        return True
    except OSError:
        return False


def _resolve_via_nslookup(host: str, dns_server: str = "8.8.8.8") -> str | None:
    """用指定 DNS 服务器解析主机名（与 ``nslookup host 8.8.8.8`` 一致）。"""
    try:
        proc = subprocess.run(
            ["nslookup", host, dns_server],
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    for line in (proc.stdout or "").splitlines():
        line = line.strip()
        if not line.startswith("Address:"):
            continue
        ip = line.split()[-1]
        if ip and ip != dns_server and not ip.endswith("#53"):
            return ip
    return None


def _check_dns_or_hint(uri: str) -> None:
    """系统 DNS 不可用时，给出可操作的修复提示（常见于仅 8.8.8.8 能解析）。"""
    host = _uri_hostname(uri)
    if not host or host in ("localhost", "127.0.0.1"):
        return
    if _system_dns_resolves(host):
        return
    ip = _resolve_via_nslookup(host)
    lines = [
        f"系统 DNS 无法解析 Neo4j 主机名: {host}",
        "（Python/neo4j 驱动使用系统 DNS，不会自动使用 nslookup 8.8.8.8）",
        "",
        "请任选一种方式修复：",
        "  1) Mac：系统设置 → 网络 → DNS，添加 8.8.8.8 或 114.114.114.114，然后重开终端",
        "  2) 代理：Clash fake-ip-filter 排除 '+.databases.neo4j.io'",
    ]
    if ip:
        lines.extend(
            [
                f"  3) 临时 hosts（公共 DNS 已解析为 {ip}）：",
                f"     sudo sh -c 'echo \"{ip} {host}\" >> /etc/hosts'",
            ]
        )
    raise OSError("\n".join(lines))


def _json_loads(raw: Any) -> dict[str, Any]:
    if not raw:
        return {}
    if isinstance(raw, dict):
        return dict(raw)
    if isinstance(raw, str):
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            return {}
    return {}


class Neo4jStore:
    """联想记忆（associative）的 Neo4j 实现。

    Args:
        uri: ``NEO4J_URI``，如 ``bolt://localhost:7687`` 或 Aura ``neo4j+s://...``
        user: ``NEO4J_USER``，默认 ``neo4j``
        password: ``NEO4J_PASSWORD``（必填）
        database: ``NEO4J_DATABASE``，默认 ``neo4j``
        auto_init_schema: 首次写入前是否自动执行 ``neo4j_schema.cypher``
    """

    def __init__(
        self,
        *,
        uri: str | None = None,
        user: str | None = None,
        password: str | None = None,
        database: str | None = None,
        auto_init_schema: bool = True,
    ) -> None:
        self.uri = uri or os.getenv("NEO4J_URI", "bolt://localhost:7687")
        self.user = user or os.getenv("NEO4J_USER", "neo4j")
        self.password = password or os.getenv("NEO4J_PASSWORD")
        if not self.password:
            raise ValueError("NEO4J_PASSWORD is required for Neo4jStore")
        self.database = database or os.getenv("NEO4J_DATABASE", "neo4j")
        self._auto_init_schema = auto_init_schema
        self._schema_ready = False
        if os.getenv("NEO4J_SKIP_DNS_CHECK", "").lower() not in ("1", "true", "yes"):
            _check_dns_or_hint(self.uri)
        self._driver: AsyncDriver = AsyncGraphDatabase.driver(
            self.uri,
            auth=(self.user, self.password),
        )

    async def close(self) -> None:
        await self._driver.close()

    # ── Schema ───────────────────────────────────────────

    async def ensure_schema(self) -> None:
        """创建约束与索引（幂等）。"""
        if self._schema_ready:
            return
        if not _SCHEMA_FILE.is_file():
            raise FileNotFoundError(f"缺少 schema 文件: {_SCHEMA_FILE}")
        text = _SCHEMA_FILE.read_text(encoding="utf-8")
        statements = [
            s.strip()
            for s in text.split(";")
            if s.strip() and not s.strip().startswith("//")
        ]
        async with self._driver.session(database=self.database) as session:
            for stmt in statements:
                await session.run(stmt)
        self._schema_ready = True

    async def _maybe_init_schema(self) -> None:
        if self._auto_init_schema:
            await self.ensure_schema()

    # ── 实体 ─────────────────────────────────────────────

    async def upsert_entity(self, entity: GraphEntity) -> str:
        """合并实体节点（按 ``namespace + name`` 唯一）。"""
        await self._maybe_init_schema()
        if not entity.id:
            entity.id = uuid.uuid4().hex
        now = now_local_str()
        if not entity.created_at:
            entity.created_at = now
        entity.updated_at = now

        cypher = """
        MERGE (e:Entity {namespace: $namespace, name: $name})
        ON CREATE SET
            e.id = $id,
            e.entity_type = $entity_type,
            e.aliases = $aliases,
            e.description = $description,
            e.metadata_json = $metadata_json,
            e.source = $source,
            e.ref_session_id = $ref_session_id,
            e.importance = $importance,
            e.created_at = $created_at,
            e.updated_at = $updated_at
        ON MATCH SET
            e.entity_type = coalesce($entity_type, e.entity_type),
            e.aliases = CASE WHEN size($aliases) > 0 THEN $aliases ELSE e.aliases END,
            e.description = coalesce($description, e.description),
            e.metadata_json = $metadata_json,
            e.importance = coalesce($importance, e.importance),
            e.updated_at = $updated_at
        RETURN e.id AS id
        """
        params = {
            "namespace": entity.namespace,
            "name": entity.name,
            "id": entity.id,
            "entity_type": entity.entity_type,
            "aliases": list(entity.aliases or []),
            "description": entity.description,
            "metadata_json": _json_dumps(entity.metadata),
            "source": entity.source,
            "ref_session_id": entity.ref_session_id,
            "importance": entity.importance,
            "created_at": entity.created_at,
            "updated_at": entity.updated_at,
        }
        record = await self._run_single(cypher, params)
        return str(record["id"])

    async def get_entity_by_name(self, namespace: str, name: str) -> GraphEntity | None:
        cypher = """
        MATCH (e:Entity {namespace: $namespace, name: $name})
        RETURN e
        LIMIT 1
        """
        record = await self._run_single(cypher, {"namespace": namespace, "name": name})
        if record is None:
            return None
        return self._node_to_entity(record["e"])

    # ── 关系 ─────────────────────────────────────────────

    async def relate(
        self,
        *,
        namespace: str,
        from_name: str,
        to_name: str,
        relation_label: str | None = None,
        from_entity_type: EntityType = "other",
        to_entity_type: EntityType = "other",
        weight: float = 1.0,
        relation_type: str = "RELATES_TO",
    ) -> str:
        """确保两端实体存在并合并关系边。返回关系 elementId。"""
        await self._maybe_init_schema()
        now = now_local_str()
        from_id = uuid.uuid4().hex
        to_id = uuid.uuid4().hex

        cypher = """
        MERGE (a:Entity {namespace: $namespace, name: $from_name})
        ON CREATE SET
            a.id = $from_id,
            a.entity_type = $from_type,
            a.created_at = $now,
            a.updated_at = $now,
            a.metadata_json = '{}',
            a.source = 'memory',
            a.importance = 0,
            a.aliases = []
        ON MATCH SET a.updated_at = $now
        MERGE (b:Entity {namespace: $namespace, name: $to_name})
        ON CREATE SET
            b.id = $to_id,
            b.entity_type = $to_type,
            b.created_at = $now,
            b.updated_at = $now,
            b.metadata_json = '{}',
            b.source = 'memory',
            b.importance = 0,
            b.aliases = []
        ON MATCH SET b.updated_at = $now
        MERGE (a)-[r:RELATES_TO]->(b)
        ON CREATE SET
            r.namespace = $namespace,
            r.relation_label = $label,
            r.relation_type = $rel_type,
            r.weight = $weight,
            r.created_at = $now
        ON MATCH SET
            r.relation_label = coalesce($label, r.relation_label),
            r.weight = coalesce($weight, r.weight)
        RETURN elementId(r) AS rel_id, a.id AS from_id, b.id AS to_id
        """
        record = await self._run_single(
            cypher,
            {
                "namespace": namespace,
                "from_name": from_name,
                "to_name": to_name,
                "from_id": from_id,
                "to_id": to_id,
                "from_type": from_entity_type,
                "to_type": to_entity_type,
                "label": relation_label,
                "rel_type": relation_type,
                "weight": weight,
                "now": now,
            },
        )
        return str(record["rel_id"])

    # ── MemoryRef ────────────────────────────────────────

    async def link_memory(
        self,
        *,
        namespace: str,
        entity_id: str,
        memory_type: LongTermMemoryType,
        memory_id: str,
        content_preview: str | None = None,
    ) -> str:
        """为实体挂载指向 episodic/semantic 的 ``MemoryRef`` 节点。"""
        await self._maybe_init_schema()
        ref_id = uuid.uuid4().hex
        now = now_local_str()
        cypher = """
        MATCH (e:Entity {namespace: $namespace, id: $entity_id})
        MERGE (m:MemoryRef {namespace: $namespace, memory_type: $memory_type, memory_id: $memory_id})
        ON CREATE SET
            m.id = $ref_id,
            m.content_preview = $preview,
            m.created_at = $now
        ON MATCH SET
            m.content_preview = coalesce($preview, m.content_preview)
        MERGE (e)-[:HAS_MEMORY]->(m)
        RETURN m.id AS ref_id
        """
        record = await self._run_single(
            cypher,
            {
                "namespace": namespace,
                "entity_id": entity_id,
                "memory_type": memory_type,
                "memory_id": memory_id,
                "ref_id": ref_id,
                "preview": content_preview,
                "now": now,
            },
        )
        return str(record["ref_id"])

    # ── 检索 ─────────────────────────────────────────────

    async def recall_neighbors(
        self,
        *,
        namespace: str,
        query: str,
        hops: int = 1,
        limit: int = 20,
        include_memory_refs: bool = True,
    ) -> AssociativeRecallResult:
        """按实体名/别名找种子节点，并扩展 ``RELATES_TO`` 邻域（1–2 跳）。"""
        hops = max(1, min(hops, 2))
        depth = "1" if hops == 1 else "1..2"
        cypher = f"""
        MATCH (seed:Entity {{namespace: $namespace}})
        WHERE seed.name = $query OR $query IN coalesce(seed.aliases, [])
        OPTIONAL MATCH (seed)-[:RELATES_TO*{depth}]-(n:Entity)
        WHERE n.namespace = $namespace AND n.id <> seed.id
        WITH seed, collect(DISTINCT n) AS neighbors
        OPTIONAL MATCH (seed)-[r:RELATES_TO]-(m:Entity)
        WHERE m.namespace = $namespace
        RETURN seed,
               [x IN neighbors WHERE x IS NOT NULL] AS neighbors,
               [x IN collect(DISTINCT r) WHERE x IS NOT NULL] AS rels
        LIMIT 1
        """
        record = await self._run_single(
            cypher, {"namespace": namespace, "query": query}
        )
        if record is None or record.get("seed") is None:
            return AssociativeRecallResult()

        seed = self._node_to_entity(record["seed"])
        entities: list[GraphEntity] = []
        for node in record.get("neighbors") or []:
            entities.append(self._node_to_entity(node))
        entities = entities[:limit]

        relations: list[GraphRelation] = []
        for rel in record.get("rels") or []:
            parsed = await self._relation_to_graph_relation(rel, namespace)
            if parsed:
                relations.append(parsed)

        memory_refs: list[GraphMemoryRef] = []
        if include_memory_refs and seed:
            memory_refs = await self._memory_refs_for_entities(
                namespace, [seed.id] + [e.id for e in entities]
            )

        return AssociativeRecallResult(
            seed=seed,
            entities=entities,
            relations=relations,
            memory_refs=memory_refs,
        )

    async def _memory_refs_for_entities(
        self, namespace: str, entity_ids: list[str]
    ) -> list[GraphMemoryRef]:
        if not entity_ids:
            return []
        cypher = """
        MATCH (e:Entity)-[:HAS_MEMORY]->(m:MemoryRef)
        WHERE e.namespace = $namespace AND e.id IN $entity_ids
        RETURN e.id AS entity_id, m
        """
        rows = await self._run_all(
            cypher, {"namespace": namespace, "entity_ids": entity_ids}
        )
        refs: list[GraphMemoryRef] = []
        for row in rows:
            refs.append(self._node_to_memory_ref(row["m"], entity_id=row["entity_id"]))
        return refs

    # ── 删除 / 清空 ───────────────────────────────────────

    async def delete_entity(self, entity_id: str, namespace: str) -> bool:
        cypher = """
        MATCH (e:Entity {namespace: $namespace, id: $entity_id})
        DETACH DELETE e
        RETURN count(e) AS deleted
        """
        record = await self._run_single(
            cypher, {"namespace": namespace, "entity_id": entity_id}
        )
        return bool(record and record.get("deleted", 0) > 0)

    async def clear_namespace(self, namespace: str) -> int:
        """删除该 namespace 下全部 Entity 与 MemoryRef 节点。"""
        cypher = """
        MATCH (n)
        WHERE n.namespace = $namespace AND (n:Entity OR n:MemoryRef)
        WITH collect(n) AS nodes
        WITH nodes, size(nodes) AS c
        FOREACH (x IN nodes | DETACH DELETE x)
        RETURN c
        """
        record = await self._run_single(cypher, {"namespace": namespace})
        return int(record.get("c", 0)) if record else 0

    # ── 内部工具 ─────────────────────────────────────────

    async def _run_single(
        self, cypher: str, params: dict[str, Any] | None = None
    ) -> dict[str, Any] | None:
        rows = await self._run_all(cypher, params)
        return rows[0] if rows else None

    async def _run_all(
        self, cypher: str, params: dict[str, Any] | None = None
    ) -> list[dict[str, Any]]:
        async with self._driver.session(database=self.database) as session:
            result = await session.run(cypher, params or {})
            return [record.data() async for record in result]

    async def _relation_to_graph_relation(
        self, rel: Any, namespace: str
    ) -> GraphRelation | None:
        """将 Neo4j Relationship 转为 GraphRelation。"""
        if rel is None:
            return None

        nodes_cypher = """
        MATCH (a)-[r]->(b)
        WHERE elementId(r) = $rel_id
        RETURN a, b, r
        LIMIT 1
        """
        rel_id = rel.element_id if hasattr(rel, "element_id") else str(rel)
        row = await self._run_single(nodes_cypher, {"rel_id": rel_id})
        if not row:
            return None
        a, b, r = row["a"], row["b"], row["r"]
        props = dict(r)
        return GraphRelation(
            id=rel_id,
            namespace=namespace,
            from_entity_id=str(a.get("id", "")),
            to_entity_id=str(b.get("id", "")),
            from_name=str(a.get("name", "")),
            to_name=str(b.get("name", "")),
            relation_type=str(props.get("relation_type", "RELATES_TO")),
            relation_label=props.get("relation_label"),
            weight=float(props.get("weight", 1.0)),
            created_at=props.get("created_at"),
        )

    @staticmethod
    def _node_to_entity(node: Any) -> GraphEntity:
        props = dict(node)
        aliases = props.get("aliases") or []
        if not isinstance(aliases, list):
            aliases = list(aliases)
        return GraphEntity(
            id=str(props.get("id", "")),
            namespace=str(props.get("namespace", "")),
            name=str(props.get("name", "")),
            entity_type=props.get("entity_type", "other"),  # type: ignore[arg-type]
            aliases=aliases,
            description=props.get("description"),
            metadata=_json_loads(props.get("metadata_json")),
            created_at=str(props.get("created_at", "")),
            updated_at=props.get("updated_at"),
            source=props.get("source", "memory"),  # type: ignore[arg-type]
            ref_session_id=props.get("ref_session_id"),
            importance=int(props.get("importance", 0)),
        )

    @staticmethod
    def _node_to_memory_ref(
        node: Any, *, entity_id: str | None = None
    ) -> GraphMemoryRef:
        props = dict(node)
        return GraphMemoryRef(
            id=str(props.get("id", "")),
            namespace=str(props.get("namespace", "")),
            memory_type=props.get("memory_type", "episodic"),  # type: ignore[arg-type]
            memory_id=str(props.get("memory_id", "")),
            entity_id=entity_id,
            content_preview=props.get("content_preview"),
            created_at=props.get("created_at"),
        )


if __name__ == "__main__":
    import asyncio

    async def _smoke() -> None:
        uri = os.getenv("NEO4J_URI", "bolt://localhost:7687")
        print("NEO4J_URI:", uri)
        store = Neo4jStore()
        ns = "mem:store_smoke:neo4j"
        try:
            await store.ensure_schema()
            print("schema ok")

            await store.relate(
                namespace=ns,
                from_name="陈艳",
                to_name="合同项目A",
                relation_label="负责",
                from_entity_type="person",
                to_entity_type="project",
            )
            result = await store.recall_neighbors(
                namespace=ns, query="陈艳", hops=1, limit=10
            )
            print("seed:", result.seed.name if result.seed else None)
            print("neighbors:", [e.name for e in result.entities])
            n = await store.clear_namespace(ns)
            print("cleared:", n)
        finally:
            await store.close()

    asyncio.run(_smoke())
