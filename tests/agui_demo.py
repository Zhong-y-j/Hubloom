"""AG-UI 最小演示：看懂一次 Agent↔前端 的事件流（与 Hubloom 业务无关）。

AG-UI 是什么？
  Agent 与用户前端之间的**标准事件协议**（多经 SSE 下发）。
  前端按事件类型更新 UI，而不是解析你们自研的 `/v1/chat` 字段。

和 Hubloom 的关系（概念对照）::

  Hubloom 现在          ≈ AG-UI
  ─────────────────     ────────────────────────────
  自研 SSE 事件名       RUN_* / TEXT_MESSAGE_* / TOOL_CALL_*
  answer 文本流         TEXT_MESSAGE_START → CONTENT* → END
  工具调用过程上屏      TOOL_CALL_START → ARGS* → END
  A2UI 载荷             （可挂在自定义/扩展事件里；本 demo 不涉及）

跑法（推荐临时装 SDK，不改项目依赖）::

    uv run --with 'ag-ui-protocol>=0.1.19' python tests/agui_demo.py

若已安装 ag-ui-protocol，也可::

    PYTHONPATH=src:. python tests/agui_demo.py
"""

from __future__ import annotations

import json
import sys
import uuid
from typing import Any, Iterator


def _require_ag_ui():
    try:
        from ag_ui.core import (  # type: ignore
            EventType,
            RunFinishedEvent,
            RunStartedEvent,
            TextMessageContentEvent,
            TextMessageEndEvent,
            TextMessageStartEvent,
            ToolCallArgsEvent,
            ToolCallEndEvent,
            ToolCallStartEvent,
        )
        from ag_ui.encoder import EventEncoder  # type: ignore
    except ImportError:
        print(
            "缺少 ag-ui-protocol。请执行：\n"
            "  uv run --with 'ag-ui-protocol>=0.1.19' python tests/agui_demo.py",
            file=sys.stderr,
        )
        raise SystemExit(1) from None
    return (
        EventType,
        EventEncoder,
        RunStartedEvent,
        RunFinishedEvent,
        TextMessageStartEvent,
        TextMessageContentEvent,
        TextMessageEndEvent,
        ToolCallStartEvent,
        ToolCallArgsEvent,
        ToolCallEndEvent,
    )


def demo_events() -> Iterator[Any]:
    """模拟一轮对话：开跑 → 说句话 → 调一次工具 → 再回复 → 结束。"""
    (
        EventType,
        _EventEncoder,
        RunStartedEvent,
        RunFinishedEvent,
        TextMessageStartEvent,
        TextMessageContentEvent,
        TextMessageEndEvent,
        ToolCallStartEvent,
        ToolCallArgsEvent,
        ToolCallEndEvent,
    ) = _require_ag_ui()

    thread_id = "thread-demo"
    run_id = f"run-{uuid.uuid4().hex[:8]}"
    msg_id = f"msg-{uuid.uuid4().hex[:8]}"
    tool_call_id = f"call-{uuid.uuid4().hex[:8]}"

    # 1) 一次 run 必须以 RUN_STARTED 开头
    yield RunStartedEvent(
        type=EventType.RUN_STARTED,
        thread_id=thread_id,
        run_id=run_id,
    )

    # 2) 流式文本：START → 若干 CONTENT(delta) → END
    yield TextMessageStartEvent(
        type=EventType.TEXT_MESSAGE_START,
        message_id=msg_id,
        role="assistant",
    )
    for chunk in ["收到。", "我先查一下列表…"]:
        yield TextMessageContentEvent(
            type=EventType.TEXT_MESSAGE_CONTENT,
            message_id=msg_id,
            delta=chunk,
        )
    yield TextMessageEndEvent(
        type=EventType.TEXT_MESSAGE_END,
        message_id=msg_id,
    )

    # 3) 工具调用（同样可流式）：START → ARGS(delta，常是 JSON 片段) → END
    #    注意：这里的 tool_call_name 是「给前端看的名字」；
    #    Hubloom 里对应 list_api / call_api 一类元工具。
    yield ToolCallStartEvent(
        type=EventType.TOOL_CALL_START,
        tool_call_id=tool_call_id,
        tool_call_name="list_api",
    )
    yield ToolCallArgsEvent(
        type=EventType.TOOL_CALL_ARGS,
        tool_call_id=tool_call_id,
        delta=json.dumps({"tag": "Demo"}, ensure_ascii=False),
    )
    yield ToolCallEndEvent(
        type=EventType.TOOL_CALL_END,
        tool_call_id=tool_call_id,
    )

    # 4) 工具结果出来后再回一段话（新 message_id）
    msg_id2 = f"msg-{uuid.uuid4().hex[:8]}"
    yield TextMessageStartEvent(
        type=EventType.TEXT_MESSAGE_START,
        message_id=msg_id2,
        role="assistant",
    )
    yield TextMessageContentEvent(
        type=EventType.TEXT_MESSAGE_CONTENT,
        message_id=msg_id2,
        delta="列表里有 3 条记录，需要我展开哪一条？",
    )
    yield TextMessageEndEvent(
        type=EventType.TEXT_MESSAGE_END,
        message_id=msg_id2,
    )

    # 5) 成功结束；失败则用 RUN_ERROR 代替 RUN_FINISHED
    yield RunFinishedEvent(
        type=EventType.RUN_FINISHED,
        thread_id=thread_id,
        run_id=run_id,
    )


def main() -> None:
    (
        _EventType,
        EventEncoder,
        *_rest,
    ) = _require_ag_ui()
    encoder = EventEncoder()

    print("=== AG-UI 事件流（SSE 编码后，前端逐条消费）===\n")
    print("流程: RUN_STARTED → 文本流 → 工具调用流 → 文本流 → RUN_FINISHED\n")

    for i, event in enumerate(demo_events(), start=1):
        sse = encoder.encode(event)
        # encoder 输出形如: data: {...}\n\n
        payload = sse.removeprefix("data: ").strip()
        try:
            obj = json.loads(payload)
            kind = obj.get("type", "?")
        except json.JSONDecodeError:
            kind = "?"
            obj = payload
        print(f"[{i:02d}] {kind}")
        print(f"     {json.dumps(obj, ensure_ascii=False)}")
        print(f"     SSE → {sse!r}\n")

    print(
        "读完后记住三点：\n"
        "  1. 前端只认标准事件 type，不认 Hubloom 私有字段名；\n"
        "  2. 文本/工具都是「开始 → 增量 → 结束」三段式；\n"
        "  3. 接到 Hubloom 时：Think/工具/Respond 的过程要映射成上述事件。"
    )


if __name__ == "__main__":
    main()
