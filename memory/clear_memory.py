"""清空长期记忆数据（Qdrant / 可选 SQLite 会话）。

用法::

    # 清空整个 Qdrant collection（所有 namespace 的 episodic + semantic）
    PYTHONPATH=. uv run python -m memory.clear_memory --qdrant-all

    # 只清空某个 namespace（Qdrant + 可选 SQLite 对话）
    PYTHONPATH=. uv run python -m memory.clear_memory --namespace mem:tester_id:default

    # 同时清空 Neo4j 联想记忆（该 namespace）
    PYTHONPATH=. uv run python -m memory.clear_memory --namespace mem:tester_id:default --with-graph
"""

from __future__ import annotations

import argparse
import asyncio

from memory.factory import create_memory_manager, GraphBackend
from memory.store import QdrantMemoryStore
from observability import setup_log


async def _clear_qdrant_collection() -> int:
    store = QdrantMemoryStore()
    try:
        deleted = await store.clear_collection()
        print(
            f"Qdrant collection {store.collection_name!r} cleared: {deleted} points"
        )
        return deleted
    finally:
        await store.close()


async def _clear_namespace(namespace: str, *, with_graph: bool) -> int:
    graph_backend: GraphBackend = "neo4j" if with_graph else "none"
    mem = create_memory_manager(namespace=namespace, graph_backend=graph_backend)
    deleted = await mem.clear_all()
    print(f"namespace {namespace!r} cleared: {deleted} items")
    return deleted


async def main(
    *,
    qdrant_all: bool,
    namespace: str | None,
    with_graph: bool,
) -> None:
    setup_log()
    if qdrant_all:
        await _clear_qdrant_collection()
        return
    if not namespace:
        raise SystemExit("请指定 --qdrant-all 或 --namespace")
    await _clear_namespace(namespace, with_graph=with_graph)


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="清空 Agent Cortex 长期记忆")
    parser.add_argument(
        "--qdrant-all",
        action="store_true",
        help="清空整个 Qdrant collection（所有 namespace）",
    )
    parser.add_argument(
        "--namespace",
        help="只清空指定 namespace（含 SQLite 对话；Qdrant 按 namespace 过滤）",
    )
    parser.add_argument(
        "--with-graph",
        action="store_true",
        help="与 --namespace 联用：同时清空 Neo4j 联想记忆",
    )
    return parser.parse_args()


if __name__ == "__main__":
    args = _parse_args()
    asyncio.run(
        main(
            qdrant_all=args.qdrant_all,
            namespace=args.namespace,
            with_graph=args.with_graph,
        )
    )
