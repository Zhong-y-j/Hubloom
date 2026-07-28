"""会话记忆最小演示：同一 session_id 下 remember → recall（含工具消息）。

用法（仓库根目录）::

    PYTHONPATH=src .venv/bin/python tests/test_memory_conversation.py
"""

from __future__ import annotations

import asyncio
import tempfile
from pathlib import Path

from core.models import Message, Role, ToolCall
from memory import create_memory_manager


async def demo_conversation_memory() -> None:
    session_id = "demo-user-1"
    call_id = "call_list_1"

    with tempfile.TemporaryDirectory() as tmp:

        # 创建记忆管理器
        memory = create_memory_manager(
            namespace=session_id,
            db_path=str(Path(tmp) / "memory.db"),
            vector_backend="none",
            graph_backend="none",
        )

        # 1、用户提问---写入记忆
        await memory.remember(
            memory_type="conversation",
            message=Message(role=Role.USER, content="帮我查一下 A 区柜子"),
        )
        # 2、助手发起工具调用（尚无最终答复）---写入记忆
        await memory.remember(
            memory_type="conversation",
            message=Message(
                role=Role.ASSISTANT,
                content="",
                tool_calls=[
                    ToolCall(
                        id=call_id,
                        name="call_api",
                        arguments={"tag": "lockers", "tool_name": "listLockers"},
                    )
                ],
            ),
        )
        # 3、工具返回结果---写入记忆
        await memory.remember(
            memory_type="conversation",
            message=Message(
                role=Role.TOOL,
                content='[{"id": "3", "zone": "A", "status": "空闲"}]',
                tool_call_id=call_id,
                name="call_api",
            ),
        )
        # 4、助手根据工具结果回复用户---写入记忆
        await memory.remember(
            memory_type="conversation",
            message=Message(
                role=Role.ASSISTANT,
                content="A 区 3 号空闲，5 号占用。",
            ),
        )

        # 5、按会话读出最近消息---召回读取会话记忆
        result = await memory.recall(memory_type="conversation", top_k=10)

        print("【session_id / namespace】", session_id)
        print("【召回条数】", len(result.messages or []))
        print("【会话历史】")
        for i, msg in enumerate(result.messages or [], 1):
            line = f"  [{i}] {msg.role.value}: {msg.content!r}"
            if msg.tool_calls:
                names = ", ".join(f"{tc.name}({tc.arguments})" for tc in msg.tool_calls)
                line += f"  | tool_calls=[{names}]"
            if msg.tool_call_id:
                line += f"  | tool_call_id={msg.tool_call_id}"
            print(line)
        await memory.clear_all()


if __name__ == "__main__":
    asyncio.run(demo_conversation_memory())
