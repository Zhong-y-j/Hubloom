"""MemoryMaintenanceWorker 单元测试（无需 Qdrant）。"""

from __future__ import annotations

import asyncio
import os
import tempfile
from unittest.mock import AsyncMock, MagicMock, patch

from core.models import LLMOutput, Message, Role, StopReason
from memory.batch_consolidator import BatchConsolidationWriteResult
from memory.memory_worker import MemoryMaintenanceWorker, WorkerConfig
from memory.store import ConversationSQLitesStore
from memory.store.consolidation_checkpoint_store import ConsolidationCheckpointStore

SAMPLE_LLM_JSON = """```json
{
  "cases": [{
    "user_intent": "查库存",
    "approach": "list_inventory",
    "tools_used": [],
    "outcome": "success",
    "user_satisfied": "unknown",
    "lesson": "先确认仓库"
  }],
  "semantic_rules": []
}
```"""


def _seed_session(store: ConversationSQLitesStore, session_id: str, turns: int) -> str:
    last_id = ""
    for i in range(turns):
        last_id = store.add_message(
            session_id,
            Message(role=Role.USER, content=f"用户问题 {i + 1}"),
        )
        last_id = store.add_message(
            session_id,
            Message(role=Role.ASSISTANT, content=f"助手回复 {i + 1}"),
        )
    return last_id


async def test_worker_skips_until_min_turns() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        db_path = os.path.join(tmp, "memory.db")
        session_id = "mem:test_worker:default"
        conv = ConversationSQLitesStore(db_path)
        _seed_session(conv, session_id, turns=2)
        conv.close()

        worker = MemoryMaintenanceWorker(
            MagicMock(),
            config=WorkerConfig(min_turns=3, db_path=db_path, vector_backend="none"),
        )
        try:
            result = await worker.run_once(consolidate=True, maintain=False)
        finally:
            await worker.close()

        assert result.sessions_scanned == 1
        assert result.sessions_consolidated == 0
        checkpoint = ConsolidationCheckpointStore(db_path).get(session_id)
        assert checkpoint is None


async def test_worker_consolidates_when_threshold_met() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        db_path = os.path.join(tmp, "memory.db")
        session_id = "mem:test_worker:default"
        conv = ConversationSQLitesStore(db_path)
        _seed_session(conv, session_id, turns=3)
        conv.close()

        llm = MagicMock()
        llm.generate = AsyncMock(
            return_value=LLMOutput(
                content=SAMPLE_LLM_JSON,
                tool_calls=[],
                stop_reason=StopReason.STOP,
            )
        )

        fake_write = BatchConsolidationWriteResult(
            cases_written=["case"],
            turns_processed=3,
        )

        worker = MemoryMaintenanceWorker(
            llm,
            config=WorkerConfig(min_turns=3, db_path=db_path, vector_backend="qdrant"),
        )
        try:
            with patch(
                "memory.memory_worker.create_memory_manager",
                return_value=MagicMock(),
            ), patch(
                "memory.memory_worker.MemoryBatchConsolidator"
            ) as consolidator_cls:
                consolidator_cls.return_value.consolidate_pending_turns = AsyncMock(
                    return_value=fake_write
                )
                result = await worker.run_once(
                    session_id=session_id,
                    consolidate=True,
                    maintain=False,
                )
        finally:
            await worker.close()

        assert result.sessions_consolidated == 1
        assert result.turns_processed == 3
        checkpoint = ConsolidationCheckpointStore(db_path).get(session_id)
        assert checkpoint is not None
        assert checkpoint.turns_consolidated == 3


async def test_worker_incremental_after_checkpoint() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        db_path = os.path.join(tmp, "memory.db")
        session_id = "mem:test_worker:default"
        conv = ConversationSQLitesStore(db_path)
        last_id = _seed_session(conv, session_id, turns=3)
        conv.close()

        checkpoint_store = ConsolidationCheckpointStore(db_path)
        checkpoint_store.upsert(session_id, last_message_id=last_id, turns_delta=3)

        conv = ConversationSQLitesStore(db_path)
        _seed_session(conv, session_id, turns=2)
        conv.close()

        worker = MemoryMaintenanceWorker(
            MagicMock(),
            config=WorkerConfig(min_turns=3, db_path=db_path, vector_backend="none"),
        )
        try:
            result = await worker.run_once(
                session_id=session_id,
                consolidate=True,
                maintain=False,
            )
        finally:
            await worker.close()

        assert result.sessions_consolidated == 0
        pending = ConversationSQLitesStore(db_path).count_user_messages(
            session_id, last_id
        )
        assert pending == 2


async def _run_unit_tests() -> None:
    await test_worker_skips_until_min_turns()
    await test_worker_consolidates_when_threshold_met()
    await test_worker_incremental_after_checkpoint()
    print("memory_worker unit tests OK")


def main() -> None:
    asyncio.run(_run_unit_tests())


if __name__ == "__main__":
    main()
