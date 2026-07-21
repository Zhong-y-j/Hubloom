"""手工跑 ``HubloomRuntime``：from_config → run_stream。

用法（仓库根目录）::

    PYTHONPATH=src .venv/bin/python tests/test_runtime.py

可选环境变量：
- ``PRESENT_MODE``：markdown | a2ui（默认 a2ui）
- ``SESSION_ID``：会话 namespace
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

_PRESENT_MODE = (os.getenv("PRESENT_MODE") or "a2ui").strip().lower()
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

    session_id = "test-runtime-8390ec11"
    task = "我想要查一下当前有哪些小区"
    config_path = _ROOT / "config" / "env.yaml"

    print(f"config={config_path}")
    print(f"session_id={session_id}")
    print(f"PRESENT_MODE={_PRESENT_MODE}")
    print(f"CLEAR_SESSION={_CLEAR_SESSION}")
    print(f"trigger={task!r}")

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
        print(f"  respond_a2ui chars={len(agent.respond_a2ui_system)}")

        # 跑前看一眼库（续跑）
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
            bearer_token="eyJhbGciOiJSUzI1NiIsImtpZCI6IjI1QTEwNTg4RDBGQ0Q4REZGMjA5NjZEREU5MzJCOTEwRjQ3MjMxN0YiLCJ4NXQiOiJKYUVGaU5EODJOX3lDV2JkNlRLNUVQUnlNWDgiLCJ0eXAiOiJhdCtqd3QifQ.eyJpc3MiOiJodHRwczovL2F1dGguemJ4LnZ6ZXJvc29mdC5jb20vIiwiZXhwIjoxNzg1ODQ2NTQ3LCJpYXQiOjE3NzgwNzA1NDcsImF1ZCI6IlpoaUJvWGkiLCJzY29wZSI6Im9wZW5pZCBaaGlCb1hpIiwianRpIjoiY2ViYTQzMTYtNzhhZC00ZmM5LTk3ZGUtMzU4Y2JlOGRkMDk0Iiwic3ViIjoiM2ExZWM4N2QtODdlMy01N2E0LTlmOWItOGYzYzk5NzkwYmM0IiwidW5pcXVlX25hbWUiOiJhZG1pbiIsIm9pX3Byc3QiOiJaaGlCb1hpX1Z1ZSIsIm9pX2F1X2lkIjoiM2ExZWQyZTgtN2E4Yi0xMGQ0LWVjOTAtYjU5YmY1Y2NhMDA0IiwicHJlZmVycmVkX3VzZXJuYW1lIjoiYWRtaW4iLCJnaXZlbl9uYW1lIjoiYWRtaW4iLCJyb2xlIjoiYWRtaW4iLCJlbWFpbCI6ImFkbWluQGFicC5pbyIsImVtYWlsX3ZlcmlmaWVkIjoiRmFsc2UiLCJwaG9uZV9udW1iZXJfdmVyaWZpZWQiOiJGYWxzZSIsImNsaWVudF9pZCI6IlpoaUJvWGlfVnVlIiwib2lfdGtuX2lkIjoiM2EyMTBmNzAtNDNlNC04MzRjLTU4MDUtODE3NDI2NjIxNDljIn0.pjfKqi0VHB8qtkosw5VbI-SD6Fc8zcqX1AEymS2uoDtmYjQqts2bM8KludmDPlbCi4l1LfBkpPORrGLas2Hho2smX5PxV5qoq3e1xX5c5fQ8vqufnGTRPhTaBOSmcm7tkQ-kxpgK5kaj_Y7bkWoAk0wCjF2HtN_FuNhuMy2RzPoo7Gg_kmttRRC2O4E4eX9AY-J7wroLS06vy47MmqhO1kKvbNWoHnttK1clIjhcS4Z3v59rFIYeJ9zU3kKa74gm4vzM4BkTIlmOS6I4PQtdEQ5OT_cVOi6jjAqe-pci6167GcrTg6Birl9sjKsSK0cbVxFJf8c9heyQ243WGTaqq2EFYqbq0QTKu4yyzVeYnz3ITEr5jsEPXo65xLj4_l5N6zyU4Oq4D5GOh5zC_pGwXDsXj2zFlmfruSe2udvaisTJzhaRiFaqsKqKFjNXn1HWA9olYuNVFvvzP9S76HiC9c0gcgUZXED1IcKAymAMjLJjrple-LCaJa5G_fQCLIY-VEgEfXWaGwZVJckrPXvNF_P7QgIQqxUnDM6WM0NC6zTjCiHJ3mXyDati45D2MC00-K9mpjs3cJO76UjJR6ArMFeBOCyQk5gSTxkobO7j-Mrj8_GVHU9-HpD8lZ7oWVGEvUxQVceLcK9mn13WyJIbmbDUUmCdieRrP8FEDTfRtes",
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
                    print("【最终回复】")
                    in_final = True
                print(item.delta, end="", flush=True)
            elif isinstance(item, A2uiMessagesEvent):
                print()
                print("-" * 60)
                print(
                    f"【A2uiMessagesEvent】replace={item.replace} "
                    f"n={len(item.messages)}"
                )
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
