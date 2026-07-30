"""Agent Step1：只测 ``src/agent`` 架构（不经 HubloomRuntime / MCP 装配）。

用法::

    PYTHONPATH=src .venv/bin/python tests/test_agent_v2_step1.py
    # 或分开跑
    PYTHONPATH=src .venv/bin/python tests/test_agent_v2_step1.py parse
    PYTHONPATH=src .venv/bin/python tests/test_agent_v2_step1.py loop
"""

from __future__ import annotations

import argparse
import asyncio
import tempfile
from collections.abc import AsyncIterator, Sequence
from pathlib import Path
from typing import Any

from agent.actions import (
    CONTROL_ASK,
    CONTROL_FINISH,
    ActAction,
    ActionParseError,
    AskAction,
    FinishAction,
    parse_decide_output,
)
from agent.events import FinalAnswerEvent, ToolCallEvent, ToolResultEvent
from agent.run import RunResult, run_stream
from core.models import LLMOutput, Message, Role, StopReason, ToolCall
from core.provider import LLMProvider, LLMStreamEvent, StreamEndEvent, StreamErrorEvent
from memory import create_memory_manager
from tools.base import BaseTool
from tools.registry import ToolRegistry
from tools.runner import ToolRunner


# ---------------------------------------------------------------------------
# Fakes：只服务 Agent 环，不碰 Runtime
# ---------------------------------------------------------------------------


class ScriptedLLM(LLMProvider):
    """按预设输出依次响应 generate_stream（测环用）。"""

    def __init__(self, outputs: Sequence[LLMOutput]) -> None:
        self._outputs = list(outputs)
        self._i = 0

    async def generate(
        self,
        messages: list[Message],
        tools: list[dict] | None = None,
        stop: list[str] | None = None,
        **kwargs: Any,
    ) -> LLMOutput:
        async for ev in self.generate_stream(
            messages, tools=tools, stop=stop, **kwargs
        ):
            if isinstance(ev, StreamEndEvent):
                return ev.output
        raise RuntimeError("ScriptedLLM: no output")

    async def generate_stream(
        self,
        messages: list[Message],
        tools: list[dict] | None = None,
        stop: list[str] | None = None,
        **kwargs: Any,
    ) -> AsyncIterator[LLMStreamEvent]:
        del messages, tools, stop, kwargs
        if self._i >= len(self._outputs):
            yield StreamErrorEvent(
                RuntimeError("ScriptedLLM: no more scripted outputs")
            )
            return
        out = self._outputs[self._i]
        self._i += 1
        yield StreamEndEvent(out)


class EchoTool(BaseTool):
    name = "echo_pet"
    description = "测试用：回显 name"
    parameters = {
        "type": "object",
        "properties": {"name": {"type": "string"}},
        "required": ["name"],
    }

    async def execute(self, **kwargs: Any) -> str:
        return f"ok:{kwargs.get('name', '')}"


def _tmp_memory():
    tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    tmp.close()
    path = tmp.name
    mem = create_memory_manager(
        namespace="agent-step1-test",
        db_path=path,
        vector_backend="none",
        graph_backend="none",
    )
    return mem, path


async def _drain(run) -> RunResult:
    result: RunResult | None = None
    async for item in run:
        if isinstance(item, RunResult):
            result = item
    if result is None:
        raise AssertionError("未收到 RunResult")
    return result


# ---------------------------------------------------------------------------
# parse
# ---------------------------------------------------------------------------


def cmd_parse() -> None:
    a = parse_decide_output(
        content="你好，我是助手。", reasoning_content="", tool_calls=[]
    )
    assert isinstance(a, FinishAction) and "你好" in a.summary
    print("ok: plain text → finish")

    a = parse_decide_output(
        content="",
        reasoning_content="",
        tool_calls=[ToolCall(id="1", name="list_api", arguments={"tag": "pet"})],
    )
    assert isinstance(a, ActAction) and a.tool_calls[0].name == "list_api"
    print("ok: business tool → act")

    a = parse_decide_output(
        content="",
        reasoning_content="",
        tool_calls=[
            ToolCall(id="2", name=CONTROL_FINISH, arguments={"summary": "已完成查询"}),
        ],
    )
    assert isinstance(a, FinishAction) and a.summary == "已完成查询"
    print("ok: agent_finish → finish")

    a = parse_decide_output(
        content="",
        reasoning_content="",
        tool_calls=[
            ToolCall(
                id="3",
                name=CONTROL_ASK,
                arguments={"question": "宠物叫什么名字？", "slots": ["name"]},
            ),
        ],
    )
    assert isinstance(a, AskAction) and "名字" in a.question
    print("ok: agent_ask → ask")

    try:
        parse_decide_output(
            content="",
            reasoning_content="",
            tool_calls=[
                ToolCall(id="a", name="call_api", arguments={}),
                ToolCall(id="b", name=CONTROL_FINISH, arguments={"summary": "x"}),
            ],
        )
        raise AssertionError("expected ActionParseError")
    except ActionParseError as exc:
        print(f"ok: mix rejected ({exc})")

    print("parse: 全部通过\n")


# ---------------------------------------------------------------------------
# loop（直接 run_stream）
# ---------------------------------------------------------------------------


async def cmd_loop() -> None:
    registry = ToolRegistry.from_tools([EchoTool()])
    runner = ToolRunner(registry)
    tools = registry.list_definitions()
    system = "测试 system：按工具协议办事。"

    # 1) 直接 finish
    mem, path = _tmp_memory()
    try:
        llm = ScriptedLLM(
            [
                LLMOutput(
                    content="",
                    tool_calls=[
                        ToolCall(
                            id="f1",
                            name=CONTROL_FINISH,
                            arguments={"summary": "你好，我是测试助手。"},
                        )
                    ],
                    stop_reason=StopReason.TOOL_CALLS,
                )
            ]
        )
        result = await _drain(
            run_stream(
                llm=llm,
                memory=mem,
                runner=runner,
                tools=tools,
                trigger=Message(role=Role.USER, content="打个招呼"),
                system_before=system,
                system_after=system,
                max_rounds=4,
            )
        )
        assert result.ok and result.status == "completed"
        assert "测试助手" in result.content
        assert result.tool_calls == 0
        print("ok: loop finish-only → completed")
    finally:
        Path(path).unlink(missing_ok=True)

    # 2) act → finish
    mem, path = _tmp_memory()
    try:
        llm = ScriptedLLM(
            [
                LLMOutput(
                    content="",
                    tool_calls=[
                        ToolCall(
                            id="a1",
                            name="echo_pet",
                            arguments={"name": "小花"},
                        )
                    ],
                    stop_reason=StopReason.TOOL_CALLS,
                ),
                LLMOutput(
                    content="",
                    tool_calls=[
                        ToolCall(
                            id="f2",
                            name=CONTROL_FINISH,
                            arguments={"summary": "已登记宠物小花。"},
                        )
                    ],
                    stop_reason=StopReason.TOOL_CALLS,
                ),
            ]
        )
        saw_tool = False
        result = None
        async for item in run_stream(
            llm=llm,
            memory=mem,
            runner=runner,
            tools=tools,
            trigger=Message(role=Role.USER, content="加宠物小花"),
            system_before=system,
            system_after=system,
            max_rounds=4,
        ):
            if isinstance(item, ToolCallEvent) and item.tool_name == "echo_pet":
                saw_tool = True
            if isinstance(item, ToolResultEvent):
                assert "ok:小花" in item.result
            if isinstance(item, FinalAnswerEvent):
                assert "小花" in item.content
            if isinstance(item, RunResult):
                result = item
        assert saw_tool and result is not None
        assert result.ok and result.status == "completed"
        assert result.tool_calls == 1
        print("ok: loop act → finish")
    finally:
        Path(path).unlink(missing_ok=True)

    # 3) ask → waiting_user
    mem, path = _tmp_memory()
    try:
        llm = ScriptedLLM(
            [
                LLMOutput(
                    content="",
                    tool_calls=[
                        ToolCall(
                            id="q1",
                            name=CONTROL_ASK,
                            arguments={"question": "请补充宠物名字。"},
                        )
                    ],
                    stop_reason=StopReason.TOOL_CALLS,
                )
            ]
        )
        result = await _drain(
            run_stream(
                llm=llm,
                memory=mem,
                runner=runner,
                tools=tools,
                trigger=Message(role=Role.USER, content="加一只宠物"),
                system_before=system,
                system_after=system,
            )
        )
        assert result.ok and result.status == "waiting_user"
        assert "名字" in result.content
        print("ok: loop ask → waiting_user")
    finally:
        Path(path).unlink(missing_ok=True)

    # 4) 流错误 → failed
    mem, path = _tmp_memory()
    try:
        llm = ScriptedLLM([])  # 无脚本 → StreamError
        result = await _drain(
            run_stream(
                llm=llm,
                memory=mem,
                runner=runner,
                tools=tools,
                trigger=Message(role=Role.USER, content="任意"),
                system_before=system,
                system_after=system,
            )
        )
        assert not result.ok and result.status == "failed"
        print("ok: loop stream error → failed")
    finally:
        Path(path).unlink(missing_ok=True)

    print("\nloop: 全部通过")


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Agent Step1 架构测试（无 Runtime）")
    parser.add_argument(
        "cmd",
        nargs="?",
        default="all",
        choices=["all", "parse", "loop"],
        help="all=parse+loop（默认）",
    )
    args = parser.parse_args(argv)
    if args.cmd in ("all", "parse"):
        cmd_parse()
    if args.cmd in ("all", "loop"):
        asyncio.run(cmd_loop())


if __name__ == "__main__":
    main()
