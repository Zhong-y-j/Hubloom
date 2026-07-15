"""离线记忆编排：定量批量提炼 + Qdrant 生命周期淘汰。

由 cron / CLI 调用，不在 CortexAgent 热路径执行。
"""

from __future__ import annotations

import asyncio
import os
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from agents.agent_log import clip, memory_log
from memory.batch_consolidator import (
    BatchConsolidationWriteResult,
    MemoryBatchConsolidator,
    split_conversation_turns,
)
from memory.factory import GraphBackend, VectorBackend, create_memory_manager
from memory.store import ConversationSQLitesStore
from memory.store.consolidation_checkpoint_store import ConsolidationCheckpointStore

if TYPE_CHECKING:
    from core.provider import LLMProvider


@dataclass(frozen=True)
class WorkerConfig:
    """离线 worker 配置。"""

    min_turns: int = 3
    db_path: str = "data/memory.db"
    vector_backend: VectorBackend = "qdrant"
    graph_backend: GraphBackend = "none"

    @classmethod
    def from_env(cls) -> WorkerConfig:
        vector = os.getenv("CORTEX_ENABLE_LONG_TERM_MEMORY", "1").strip().lower()
        enable_ltm = vector not in ("0", "false", "no", "off")
        return cls(
            min_turns=max(1, int(os.getenv("CORTEX_CONSOLIDATE_MIN_TURNS", "3"))),
            db_path=os.getenv("CORTEX_MEMORY_DB", "data/memory.db"),
            vector_backend="qdrant" if enable_ltm else "none",
            graph_backend="none",
        )


@dataclass
class SessionConsolidationResult:
    session_id: str
    pending_turns: int
    consolidated: bool = False
    write_result: BatchConsolidationWriteResult | None = None
    error: str | None = None


@dataclass
class WorkerRunResult:
    sessions_scanned: int = 0
    sessions_consolidated: int = 0
    turns_processed: int = 0
    cases_written: int = 0
    rules_written: int = 0
    evicted: int = 0
    session_results: list[SessionConsolidationResult] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)


class MemoryMaintenanceWorker:
    """定量提炼 conversation → Qdrant；定时执行 TTL/容量淘汰。"""

    def __init__(
        self,
        llm: LLMProvider,
        *,
        config: WorkerConfig | None = None,
    ) -> None:
        self._llm = llm
        self._config = config or WorkerConfig.from_env()
        self._conversation_store = ConversationSQLitesStore(self._config.db_path)
        self._checkpoint_store = ConsolidationCheckpointStore(self._config.db_path)

    async def close(self) -> None:
        self._conversation_store.close()
        self._checkpoint_store.close()

    async def run_once(
        self,
        *,
        session_id: str | None = None,
        consolidate: bool = True,
        maintain: bool = True,
    ) -> WorkerRunResult:
        """扫描会话：满 N 轮则提炼；最后按现有策略做 Qdrant 淘汰。"""
        result = WorkerRunResult()
        sessions = await self._list_sessions(session_id)
        result.sessions_scanned = len(sessions)

        if consolidate and self._config.vector_backend != "none":
            for meta in sessions:
                sid = str(meta["session_id"])
                part = await self._maybe_consolidate_session(sid)
                result.session_results.append(part)
                if part.error:
                    result.errors.append(f"{sid}: {part.error}")
                if part.consolidated and part.write_result:
                    result.sessions_consolidated += 1
                    result.turns_processed += part.write_result.turns_processed
                    result.cases_written += len(part.write_result.cases_written)
                    result.rules_written += len(
                        part.write_result.semantic_rules_written
                    )

        if maintain and self._config.vector_backend != "none":
            maintain_targets = [str(s["session_id"]) for s in sessions]
            seen: set[str] = set()
            for namespace in maintain_targets:
                if namespace in seen:
                    continue
                seen.add(namespace)
                try:
                    evicted = await self._run_maintenance(namespace)
                    result.evicted += evicted
                except Exception as exc:
                    msg = f"maintenance {namespace}: {exc}"
                    result.errors.append(msg)
                    memory_log(
                        "worker maintenance failed",
                        namespace=namespace,
                        error=type(exc).__name__,
                        detail=clip(str(exc), 120),
                    )

        memory_log(
            "worker run_once done",
            scanned=result.sessions_scanned,
            consolidated=result.sessions_consolidated,
            turns=result.turns_processed,
            cases=result.cases_written,
            rules=result.rules_written,
            evicted=result.evicted,
            errors=len(result.errors),
        )
        return result

    async def _list_sessions(
        self, session_id: str | None
    ) -> list[dict[str, object]]:
        if session_id:
            count = await asyncio.to_thread(
                self._conversation_store.count, session_id
            )
            if count <= 0:
                return []
            return [{"session_id": session_id, "message_count": count}]
        return await asyncio.to_thread(self._conversation_store.list_sessions)

    async def _maybe_consolidate_session(
        self, session_id: str
    ) -> SessionConsolidationResult:
        checkpoint = self._checkpoint_store.get(session_id)
        after_id = checkpoint.last_message_id if checkpoint else None

        pending_user_turns = await asyncio.to_thread(
            self._conversation_store.count_user_messages,
            session_id,
            after_id,
        )
        outcome = SessionConsolidationResult(
            session_id=session_id,
            pending_turns=pending_user_turns,
        )

        if pending_user_turns < self._config.min_turns:
            return outcome

        records = await asyncio.to_thread(
            self._conversation_store.get_records_after,
            session_id,
            after_id,
        )
        turns = split_conversation_turns(records)
        if len(turns) < self._config.min_turns:
            return outcome

        try:
            mem = create_memory_manager(
                namespace=session_id,
                db_path=self._config.db_path,
                vector_backend=self._config.vector_backend,
                graph_backend=self._config.graph_backend,
            )
            consolidator = MemoryBatchConsolidator(mem, self._llm)
            write_result = await consolidator.consolidate_pending_turns(
                session_id,
                turns,
            )
            outcome.write_result = write_result
            outcome.consolidated = bool(
                write_result.turns_processed > 0 and not write_result.skipped
            )
            if write_result.error:
                outcome.error = write_result.error

            if turns and outcome.consolidated:
                last_id = turns[-1][-1].id
                self._checkpoint_store.upsert(
                    session_id,
                    last_message_id=last_id,
                    turns_delta=write_result.turns_processed,
                )
                memory_log(
                    "worker consolidated session",
                    session_id=session_id,
                    pending_turns=pending_user_turns,
                    processed=write_result.turns_processed,
                    cases=len(write_result.cases_written),
                    rules=len(write_result.semantic_rules_written),
                    checkpoint=last_id,
                )
        except Exception as exc:
            outcome.error = str(exc)
            memory_log(
                "worker consolidate failed",
                session_id=session_id,
                error=type(exc).__name__,
                detail=clip(str(exc), 120),
            )
        return outcome

    async def _run_maintenance(self, namespace: str) -> int:
        mem = create_memory_manager(
            namespace=namespace,
            db_path=self._config.db_path,
            vector_backend=self._config.vector_backend,
            graph_backend=self._config.graph_backend,
        )
        evicted = await mem.run_maintenance()
        if evicted:
            memory_log("worker maintenance", namespace=namespace, evicted=evicted)
        return evicted
