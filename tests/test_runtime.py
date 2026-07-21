"""手工跑 ``HubloomRuntime``：from_config → run_stream。

用法（仓库根目录）::

    PYTHONPATH=src .venv/bin/python tests/test_runtime.py

可选环境变量：
- ``PRESENT_MODE``：markdown | a2ui（默认 markdown）
- ``SESSION_ID``：会话 namespace（建议每次换新的，避免历史污染）
- ``TASK``：触发用户话
- ``CLEAR_SESSION=1``：结束后清空本 session conversation
"""

from __future__ import annotations

import asyncio
import os
from pathlib import Path

from agent.assemble import load_conversation
from agent.events import (
    A2uiMessagesEvent,
    ErrorEvent,
    FinalAnswerDeltaEvent,
    FinalAnswerEvent,
    PhaseEvent,
    RunStatsEvent,
    ThoughtDeltaEvent,
    ToolCallEvent,
    ToolResultEvent,
)
from agent.run import RunResult
from core.models import Message, Role
from memory.manager import MemoryManager
from runtime import HubloomRuntime

_PRESENT_MODE = "a2ui"
_ROOT = Path(__file__).resolve().parents[1]
_CLEAR_SESSION = os.getenv("CLEAR_SESSION", "").strip().lower() in {
    "1",
    "true",
    "yes",
}


async def print_stored_conversation(
    memory: MemoryManager,
    *,
    title: str = "库内会话",
    top_k: int = 40,
) -> list[Message]:
    rows = await load_conversation(memory, top_k=top_k)
    print(f"【{title}】共 {len(rows)} 条（conversation）")
    for i, m in enumerate(rows):
        preview = m.content if isinstance(m.content, str) else str(m.content)
        if len(preview) > 160:
            preview = preview[:160] + "…"
        extra = ""
        if m.tool_calls:
            extra = " tool_calls=" + ",".join(tc.name for tc in m.tool_calls)
        if m.tool_call_id:
            extra += f" tool_call_id={m.tool_call_id}"
        print(f"  db[{i}] {m.role.value}: {preview!r}{extra}")
    return rows


async def test_runtime() -> None:
    if _PRESENT_MODE not in {"markdown", "a2ui"}:
        raise SystemExit(f"PRESENT_MODE 无效: {_PRESENT_MODE!r}，可选 markdown / a2ui")

    session_id = "test-runtime-11111"
    task = "我当前想要添加一个宠物"
    config_path = _ROOT / "config" / "env.yaml"

    print(f"config={config_path}")
    print(f"session_id={session_id}")
    print(f"PRESENT_MODE={_PRESENT_MODE}")
    print(f"CLEAR_SESSION={_CLEAR_SESSION}")
    print(f"trigger={task!r}")
    print("注：Respond(markdown/a2ui) 均只吃本轮末次 Think，不带 tool 原文")

    agent = await HubloomRuntime.from_config_file(
        config_path,
        default_present_mode=_PRESENT_MODE,  # type: ignore[arg-type]
    )
    try:
        n_mcp = len(agent._mcp_tools)
        print(
            f"【Runtime 已装配】mcp_tools={n_mcp} max_think_rounds={agent.max_think_rounds}"
        )
        print(f"  think_system chars={len(agent.think_system)}")
        print(f"  think_system_after chars={len(agent.think_system_after)}")
        print(f"  respond_markdown chars={len(agent.respond_markdown_system)}")
        print(f"  respond_a2ui chars={len(agent.respond_a2ui_system)}")

        peek = agent._make_memory(session_id)
        existing = await load_conversation(peek)
        if existing:
            await print_stored_conversation(peek, title="已有会话（续跑）")

        print("=" * 60)
        print("【HubloomRuntime.run_stream】")
        run_result: RunResult | None = None
        in_final = False

        async for item in agent.run_stream(
            Message(role=Role.USER, content=task),
            session_id=session_id,
            present_mode=_PRESENT_MODE,  # type: ignore[arg-type]
            trigger_source="user",
            bearer_token=(
                os.getenv("MCP_TOKEN") or os.getenv("HUBLOOM_BEARER") or ""
            ).strip()
            or None,
        ):
            if isinstance(item, PhaseEvent):
                print()
                print("-" * 60)
                print(f"【PhaseEvent】phase={item.phase} route={item.route}")
            elif isinstance(item, ThoughtDeltaEvent):
                if not in_final:
                    print(item.delta, end="", flush=True)
            elif isinstance(item, ToolCallEvent):
                print(f"\n  → call {item.tool_name} {item.args}")
            elif isinstance(item, ToolResultEvent):
                flag = "ERR" if item.is_error else "OK"
                preview = (item.result or "")[:500]
                print(f"  ← [{flag}] {item.tool_name}: {preview}")
            elif isinstance(item, FinalAnswerDeltaEvent):
                if not in_final:
                    print()
                    print("-" * 60)
                    print("【最终回复 / Respond】")
                    in_final = True
                print(item.delta, end="", flush=True)
            elif isinstance(item, A2uiMessagesEvent):
                print()
                print("-" * 60)
                print(
                    f"【A2uiMessagesEvent】replace={item.replace} "
                    f"n={len(item.messages)}"
                )
                for i, msg in enumerate(item.messages):
                    keys = ",".join(
                        k
                        for k in (
                            "createSurface",
                            "updateComponents",
                            "updateDataModel",
                            "deleteSurface",
                        )
                        if k in msg
                    )
                    print(f"  [{i}] {keys or list(msg.keys())[:3]}")
            elif isinstance(item, FinalAnswerEvent):
                print()
                print("-" * 60)
                print("【FinalAnswerEvent】len=", len(item.content or ""))
            elif isinstance(item, RunStatsEvent):
                print()
                print("-" * 60)
                print(
                    "【RunStatsEvent】"
                    f" steps={item.steps}"
                    f" tool_calls={item.tool_calls}"
                    f" tool_errors={item.tool_errors}"
                    f" elapsed_ms={item.elapsed_ms}"
                )
            elif isinstance(item, ErrorEvent):
                print(f"\n[error] {item.error} recoverable={item.recoverable}")
            elif isinstance(item, RunResult):
                run_result = item

        print()
        print("=" * 60)
        print("【RunResult】")
        if run_result is None:
            print("  （未收到）")
        else:
            print("  ok:", run_result.ok)
            print("  present_mode:", run_result.present_mode)
            print("  think_rounds:", run_result.think_rounds)
            print("  tool_calls:", run_result.tool_calls)
            print("  tool_errors:", run_result.tool_errors)
            print("  elapsed_ms:", run_result.elapsed_ms)
            print("  a2ui_messages:", len(run_result.a2ui_messages))
            print("  error:", run_result.error or "(none)")
            preview = run_result.content or ""
            if len(preview) > 500:
                preview = preview[:500] + "…"
            print("  content:", preview)

        memory = agent._make_memory(session_id)
        await print_stored_conversation(memory, title="run 后库内会话")

        if _CLEAR_SESSION:
            n = await memory.clear_all(memory_type="conversation")
            print(f"已清空 session conversation（deleted={n}）")
        else:
            print(
                f"\n会话已保留：session_id={session_id} "
                f"db={agent.cfg.memory_db_path or 'data/memory.db'}\n"
                "清理：CLEAR_SESSION=1 PYTHONPATH=src .venv/bin/python tests/test_runtime.py"
            )
    finally:
        await agent.aclose()
        print("\n=== Runtime 已 aclose（MCP 已关闭）===")


if __name__ == "__main__":
    from observability import setup_log

    setup_log()
    asyncio.run(test_runtime())
