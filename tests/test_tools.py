"""演示如何像 Runtime._make_runner 一样装配工具面，并模拟一次 LLM tool_call。

用法::

    PYTHONPATH=src .venv/bin/python -m pytest tests/test_tools.py -q
"""

from __future__ import annotations

import asyncio
import tempfile
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock

from agent.loop.execute import ExecuteResult, execute
from core.models import ToolCall
from mcp_adapter.client.result import ToolTransportResult
from mcp_adapter.gateway.catalog import GatewayCatalog, GroupCatalog, ToolRef
from memory import create_memory_manager
from tools.builtin.api_tools import build_api_tools
from tools.builtin.memory_tool import SearchMemoryTool
from tools.builtin.skill_tools import build_skill_tools, clear_read_skill_turn_state
from tools.registry import ToolRegistry
from tools.runner import ToolRunner

_SKILLS_DIR = Path(__file__).resolve().parents[1] / "skills"


def _stub_mcp_tools() -> list[Any]:
    """单元测试不拉真 MCP：用最小 catalog + client 得到 list_api / call_api。"""
    catalog = GatewayCatalog(
        groups={
            "pets": GroupCatalog(
                tag="pets",
                description="demo",
                tools=[ToolRef("listPets", "GET", "/pets", "list")],
            )
        }
    )
    client = MagicMock()
    client.list_tools = AsyncMock(
        return_value=[{"name": "listPets", "description": "list", "parameters": {}}]
    )
    client.execute_tool = AsyncMock(
        return_value=ToolTransportResult(
            tool_name="listPets",
            arguments={},
            transport_ok=True,
            http_status=200,
            body="[]",
        )
    )
    return build_api_tools(catalog, client)


def test_make_runner_like_runtime() -> None:
    """对齐 runtime._make_runner：SearchMemory + skills + mcp 元工具。"""

    async def _run() -> None:
        clear_read_skill_turn_state()
        with tempfile.TemporaryDirectory() as tmp:
            memory = create_memory_manager(
                namespace="test-tools",
                db_path=str(Path(tmp) / "memory.db"),
                vector_backend="none",
                graph_backend="none",
            )

            # —— 与 HubloomRuntime._make_runner 同一形状 ——
            skill_tools = build_skill_tools(skills_dir=_SKILLS_DIR)
            mcp_tools = _stub_mcp_tools()  # 生产里是 self._mcp_tools
            tools: list[Any] = [SearchMemoryTool(memory), *skill_tools, *mcp_tools]
            registry = ToolRegistry.from_tools(tools)
            print(registry.list_definitions())
            runner = ToolRunner(registry)
            tool_defs = registry.list_definitions()

            names = {d["name"] for d in tool_defs}
            assert {"search_memory", "read_skill", "list_api", "call_api"} <= names

            # 模拟 LLM 已产出 tool_calls → Execute（不调真实模型）
            result: ExecuteResult | None = None
            async for item in execute(
                [
                    ToolCall(
                        id="c1",
                        name="list_api",
                        arguments={"tag": "pets"},
                    )
                ],
                runner,
            ):
                if isinstance(item, ExecuteResult):
                    result = item

            assert result is not None
            assert result.results[0][2] is False
            assert "listPets" in result.results[0][1]

    asyncio.run(_run())


if __name__ == "__main__":
    test_make_runner_like_runtime()
