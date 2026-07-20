// Hubloom · associative 联想记忆 Schema（Neo4j 5+）
// 由 Neo4jStore.ensure_schema() 执行；可重复运行（IF NOT EXISTS）

CREATE CONSTRAINT entity_id_unique IF NOT EXISTS
FOR (e:Entity) REQUIRE e.id IS UNIQUE;

CREATE CONSTRAINT memory_ref_id_unique IF NOT EXISTS
FOR (m:MemoryRef) REQUIRE m.id IS UNIQUE;

CREATE CONSTRAINT entity_ns_name_unique IF NOT EXISTS
FOR (e:Entity) REQUIRE (e.namespace, e.name) IS UNIQUE;

CREATE INDEX entity_namespace IF NOT EXISTS FOR (e:Entity) ON (e.namespace);
CREATE INDEX entity_type IF NOT EXISTS FOR (e:Entity) ON (e.entity_type);
CREATE INDEX memory_ref_namespace IF NOT EXISTS FOR (m:MemoryRef) ON (m.namespace);
CREATE INDEX memory_ref_lookup IF NOT EXISTS FOR (m:MemoryRef) ON (m.memory_type, m.memory_id);
