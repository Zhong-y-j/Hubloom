"""手工跑 Orchestrator：``run_stream``（Think ↔ Execute → Respond）。

用法（仓库根目录）::

    PYTHONPATH=src .venv/bin/python tests/test_agent.py

会话写入 ``config/env.yaml`` 的 ``memory.db_path``（默认 ``data/memory.db``），
按 ``session_id`` 隔离。默认**不清理**，便于事后查库。
"""

from __future__ import annotations

import asyncio
import os
from pathlib import Path

from agent.assemble import (
    build_respond_a2ui_system,
    build_respond_markdown_system,
    build_think_systems,
    load_conversation,
)
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
from agent.run import RunResult, run_stream
from config import HubloomConfig
from context import set_request_context
from core.factory import create_llm
from core.models import Message, Role
from mcp_adapter.discovery import AgentMcpSetup, load_agent_mcp_bindings
from memory import create_memory_manager
from memory.manager import MemoryManager
from skill import load_skills
from tools.builtin.memory_tool import SearchMemoryTool
from tools.registry import ToolRegistry
from tools.runner import ToolRunner

_PRESENT_MODE = (os.getenv("PRESENT_MODE") or "a2ui").strip().lower()  # markdown | a2ui
_ROOT = Path(__file__).resolve().parents[1]
_SRC = _ROOT / "src"
_MAX_THINK_ROUNDS = 5
_CLEAR_SESSION = os.getenv("CLEAR_SESSION", "").strip().lower() in {
    "1",
    "true",
    "yes",
}


def _db_path(cfg: HubloomConfig) -> str:
    raw = (cfg.memory_db_path or "data/memory.db").strip() or "data/memory.db"
    path = Path(raw)
    if not path.is_absolute():
        path = _ROOT / path
    path.parent.mkdir(parents=True, exist_ok=True)
    return str(path)


def _skills_dir(cfg: HubloomConfig) -> Path:
    raw = (cfg.skills_dir or "skills").strip() or "skills"
    path = Path(raw)
    if not path.is_absolute():
        path = _ROOT / path
    return path


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


async def load_tools(
    cfg: HubloomConfig,
    memory: MemoryManager,
) -> tuple[ToolRegistry, AgentMcpSetup | None]:
    tools: list = [SearchMemoryTool(memory)]
    mcp_setup: AgentMcpSetup | None = None

    if cfg.enable_mcp:
        swagger = (cfg.mcp_swagger_url or "").strip()
        if not swagger:
            raise SystemExit("mcp.enable=true 但未配置 mcp.swagger_url")

        set_request_context(
            mcp_auth_scheme=cfg.mcp_auth_scheme,
            mcp_swagger_url=swagger,
            mcp_base_url=cfg.mcp_base_url,
        )

        child_env: dict[str, str] = {}
        if cfg.mcp_auth_scheme:
            child_env["MCP_AUTH_SCHEME"] = str(cfg.mcp_auth_scheme).strip()
        if cfg.mcp_token:
            child_env["MCP_TOKEN"] = str(cfg.mcp_token).strip()

        mcp_setup = await load_agent_mcp_bindings(
            swagger_url=swagger,
            base_url=cfg.mcp_base_url,
            env=child_env or None,
            cwd=str(_SRC),
        )
        tools.extend(mcp_setup.bindings.tools)

    return ToolRegistry.from_tools(tools), mcp_setup


def _print_tools(registry: ToolRegistry) -> None:
    defs = registry.list_definitions()
    print(f"【已装配 tools】共 {len(defs)} 个")
    for d in defs:
        params = (d.get("parameters") or {}).get("properties") or {}
        keys = ", ".join(params.keys()) if params else "(无参)"
        print(f"  • {d['name']}: {d.get('description', '')[:80]}")
        print(f"    参数: {keys}")


async def test_agent() -> None:
    if _PRESENT_MODE not in {"markdown", "a2ui"}:
        raise SystemExit(f"PRESENT_MODE 无效: {_PRESENT_MODE!r}，可选 markdown / a2ui")

    cfg = HubloomConfig.from_file(_ROOT / "config" / "env.yaml")
    if not (cfg.openai_api_key or "").strip():
        raise SystemExit("config/env.yaml 未配置 llm.api_key")

    llm = create_llm(
        api_key=cfg.openai_api_key,
        model=cfg.openai_model,
        base_url=cfg.openai_base_url,
    )

    session_id = (os.getenv("SESSION_ID") or "").strip() or "test-agent-8390ec88"
    db_path = _db_path(cfg)
    memory = create_memory_manager(
        namespace=session_id,
        db_path=db_path,
        vector_backend="none",
        graph_backend="none",
    )
    set_request_context(session_id=session_id)

    print(f"session_id={session_id}")
    print(f"memory_db={db_path}")
    print(f"PRESENT_MODE={_PRESENT_MODE}")
    print(f"CLEAR_SESSION={_CLEAR_SESSION}")

    mcp_setup: AgentMcpSetup | None = None
    try:
        registry, mcp_setup = await load_tools(cfg, memory)
        runner = ToolRunner(registry)
        tool_defs = registry.list_definitions()
        skills_dir = _skills_dir(cfg)

        think_system, think_system_after = build_think_systems(
            skills_dir=skills_dir,
            skills_exclude=cfg.skills_exclude,
            catalog=None if mcp_setup is None else mcp_setup.catalog,
        )
        respond_system = (
            build_respond_a2ui_system()
            if _PRESENT_MODE == "a2ui"
            else build_respond_markdown_system()
        )

        _print_tools(registry)
        print(f"skills_dir={skills_dir}")
        print(
            "skills:",
            [s["name"] for s in load_skills(skills_dir, exclude=cfg.skills_exclude)],
        )

        existing = await load_conversation(memory)
        if existing:
            await print_stored_conversation(memory, title="已有会话（续跑）")

        task = (os.getenv("TASK") or "").strip() or "帮我添加一个宠物"
        trigger = Message(role=Role.USER, content=task)
        print(f"trigger={task!r}")

        print("=" * 60)
        print("【run_stream】")
        run_result: RunResult | None = None
        in_final = False

        async for item in run_stream(
            llm=llm,
            memory=memory,
            runner=runner,
            tools=tool_defs,
            trigger=trigger,
            think_system=think_system,
            think_system_after=think_system_after,
            respond_system=respond_system,
            present_mode=_PRESENT_MODE,  # type: ignore[arg-type]
            max_think_rounds=_MAX_THINK_ROUNDS,
            trigger_source="user",
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

        await print_stored_conversation(memory, title="run 后库内会话")
    finally:
        if mcp_setup is not None:
            try:
                await mcp_setup.bindings.client.close()
                print("\n=== MCP 连接已关闭 ===")
            except Exception:
                pass
        if _CLEAR_SESSION:
            try:
                n = await memory.clear_all(memory_type="conversation")
                print(f"已清空 session conversation（deleted={n}）")
            except Exception:
                pass
        else:
            print(
                f"\n会话已保留：session_id={session_id} db={db_path}\n"
                "清理：CLEAR_SESSION=1 PYTHONPATH=src .venv/bin/python tests/test_agent.py"
            )


if __name__ == "__main__":
    from observability import setup_log

    setup_log()
    asyncio.run(test_agent())
