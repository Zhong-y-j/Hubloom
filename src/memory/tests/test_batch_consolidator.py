"""MemoryBatchConsolidator 单元测试与可选集成 smoke test。

运行单元测试（无需 Qdrant）::

    PYTHONPATH=. uv run python -m memory.tests.test_batch_consolidator

集成测试（需 OPENAI_API_KEY + Qdrant）::

    PYTHONPATH=. uv run python -m memory.tests.test_batch_consolidator --integration
"""

from __future__ import annotations

import argparse
import asyncio
from unittest.mock import AsyncMock, MagicMock

from core.models import LLMOutput, Message, Role, StopReason, ToolCall
from memory.batch_consolidator import (
    MemoryBatchConsolidator,
    format_conversation_segment,
    split_conversation_turns,
)
from memory.experience_case import BatchExtractionResult, ExperienceCase, SemanticRule
from memory.store.conversation_sqlite_store import ConversationMessageRecord

SAMPLE_LLM_JSON = """```json
{
  "cases": [{
    "user_intent": "查询库存",
    "approach": "调用 list_inventory",
    "tools_used": [{"name": "list_inventory", "args_summary": "{}", "success": true}],
    "outcome": "success",
    "user_satisfied": "unknown",
    "lesson": "库存查询直接用 list_inventory"
  }],
  "semantic_rules": [{
    "rule": "库存问题优先 list_inventory",
    "confidence": "medium",
    "domain": "inventory"
  }]
}
```"""


def _records() -> list[ConversationMessageRecord]:
    return [
        ConversationMessageRecord(
            id="m1",
            message=Message(role=Role.USER, content="帮我查库存"),
        ),
        ConversationMessageRecord(
            id="m2",
            message=Message(
                role=Role.ASSISTANT,
                content="正在查询",
                tool_calls=[
                    ToolCall(id="c1", name="list_inventory", arguments={}),
                ],
            ),
        ),
        ConversationMessageRecord(
            id="m3",
            message=Message(
                role=Role.TOOL,
                content='{"items": []}',
                tool_call_id="c1",
                name="list_inventory",
            ),
        ),
        ConversationMessageRecord(
            id="m4",
            message=Message(role=Role.ASSISTANT, content="当前库存为空"),
        ),
    ]


def test_format_conversation_segment() -> None:
    text = format_conversation_segment(_records())
    assert "[m1] user:" in text
    assert "list_inventory" in text
    assert "[m3] tool/list_inventory:" in text


def test_split_conversation_turns() -> None:
    records = _records() + [
        ConversationMessageRecord(
            id="m5",
            message=Message(role=Role.USER, content="谢谢"),
        ),
        ConversationMessageRecord(
            id="m6",
            message=Message(role=Role.ASSISTANT, content="不客气"),
        ),
    ]
    turns = split_conversation_turns(records)
    assert len(turns) == 2
    assert turns[0][0].id == "m1"
    assert turns[1][0].id == "m5"


async def test_apply_extraction_writes_to_memory() -> None:
    mem = MagicMock()
    mem.remember = AsyncMock(return_value="id-1")
    consolidator = MemoryBatchConsolidator(mem, llm=MagicMock())

    extracted = BatchExtractionResult(
        cases=[
            ExperienceCase(
                user_intent="查库存",
                approach="list_inventory",
                lesson="直接查",
            )
        ],
        semantic_rules=[
            SemanticRule(rule="库存用 list_inventory", confidence="high"),
        ],
    )
    result = await consolidator.apply_extraction(extracted)
    assert result.total_written == 2
    assert mem.remember.await_count == 2
    assert mem.remember.await_args_list[0].kwargs["memory_type"] == "episodic"
    assert mem.remember.await_args_list[1].kwargs["memory_type"] == "semantic"


async def test_consolidate_segment_with_mock_llm() -> None:
    mem = MagicMock()
    mem.remember = AsyncMock(return_value="id-1")
    llm = MagicMock()
    llm.generate = AsyncMock(
        return_value=LLMOutput(
            content=SAMPLE_LLM_JSON,
            tool_calls=[],
            stop_reason=StopReason.STOP,
        )
    )
    consolidator = MemoryBatchConsolidator(mem, llm)
    result = await consolidator.consolidate_segment(
        "mem:test:default",
        _records(),
        route="thought",
    )
    assert not result.skipped
    assert len(result.cases_written) == 1
    assert len(result.semantic_rules_written) == 1
    llm.generate.assert_awaited_once()


async def _integration_main(namespace: str) -> None:
    from core.factory import create_llm
    from core.models import Message, Role
    from memory.factory import create_memory_manager
    from observability import setup_log

    setup_log()
    mem = create_memory_manager(namespace=namespace, graph_backend="none")
    await mem.clear_all()

    await mem.remember(
        memory_type="conversation",
        message=Message(role=Role.USER, content="帮我查当前库存"),
    )
    await mem.remember(
        memory_type="conversation",
        message=Message(role=Role.ASSISTANT, content="好的，我先查询库存列表。"),
    )

    consolidator = MemoryBatchConsolidator(mem, create_llm())
    result = await consolidator.consolidate_session(namespace, route="thought")
    print("--- batch consolidate ---")
    print("skipped:", result.skipped)
    print("turns:", result.turns_processed)
    print("cases:", result.cases_written)
    print("rules:", result.semantic_rules_written)
    if result.error:
        print("error:", result.error)

    if result.cases_written:
        hits = await mem.recall(query="库存", mode="hybrid", top_k=3)
        print("recall:", [i.content for i in hits.items or []])


async def _run_unit_tests() -> None:
    test_format_conversation_segment()
    test_split_conversation_turns()
    await test_apply_extraction_writes_to_memory()
    await test_consolidate_segment_with_mock_llm()
    print("batch_consolidator unit tests OK")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--integration",
        action="store_true",
        help="运行集成 smoke test（需 LLM + Qdrant）",
    )
    parser.add_argument(
        "--namespace",
        default="mem:test_batch:default",
        help="集成测试 namespace",
    )
    args = parser.parse_args()

    if args.integration:
        asyncio.run(_integration_main(args.namespace))
    else:
        asyncio.run(_run_unit_tests())


if __name__ == "__main__":
    main()
