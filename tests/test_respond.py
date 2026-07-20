"""手工跑完整链路：Think ↔ Execute → Respond，全程经 conversation 读写。

用法（仓库根目录）::

    PYTHONPATH=src .venv/bin/python tests/test_respond.py

会话写入 ``config/env.yaml`` 的 ``memory.db_path``（默认 ``data/memory.db``），
按 ``session_id``（namespace）隔离。默认**不清理**，便于事后查库。
"""

from __future__ import annotations

import asyncio
import os
from pathlib import Path

from agent.events import (
    ErrorEvent,
    FinalAnswerDeltaEvent,
    FinalAnswerEvent,
    ThoughtDeltaEvent,
    ToolCallEvent,
    ToolResultEvent,
)
from agent.loop.execute import ExecuteResult, execute
from agent.loop.respond import RespondResult, respond
from agent.loop.think import ThinkDecision, think
from agent.prompts import RESPOND_MARKDOWN_SYSTEM, THINK_SYSTEM
from config import HubloomConfig
from core.factory import create_llm
from core.models import Message, Role
from context import set_request_context
from mcp_adapter.discovery import AgentMcpSetup, load_agent_mcp_bindings
from mcp_adapter.gateway.catalog import format_catalog_for_prompt
from memory import ContextAssembler, create_memory_manager
from memory.manager import MemoryManager
from skill import build_skills_prompt, load_skills
from tools.builtin.memory_tool import SearchMemoryTool
from tools.registry import ToolRegistry
from tools.runner import ToolRunner

_ROOT = Path(__file__).resolve().parents[1]
_SRC = _ROOT / "src"
_MAX_THINK_ROUNDS = 5
# 设 CLEAR_SESSION=1 时 finally 清空本 session 会话表
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


# ─── conversation 读写（正式路径：MemoryManager） ───


async def save_message(
    memory: MemoryManager,
    message: Message,
    *,
    source: str = "agent",
) -> str:
    """写入 conversation 表。"""
    return await memory.remember(
        memory_type="conversation",
        message=message,
        source=source,
    )


async def load_histories(
    memory: MemoryManager,
    *,
    top_k: int = 40,
) -> list[Message]:
    """从 conversation 表召回最近消息（时间正序）。"""
    recalled = await memory.recall(memory_type="conversation", top_k=top_k)
    return list(recalled.messages or [])


async def print_stored_conversation(
    memory: MemoryManager,
    *,
    title: str = "库内会话",
    top_k: int = 40,
) -> list[Message]:
    """从 memory 再读一遍并打印，确认落库。"""
    rows = await load_histories(memory, top_k=top_k)
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


async def assemble_from_memory(
    memory: MemoryManager,
    *,
    system_prompt: str,
    task: str = "",
    history_limit: int = 40,
) -> list[Message]:
    """召回会话历史 → ContextAssembler；``task`` 为本轮 USER（已落库则去重）。"""
    histories = await load_histories(memory, top_k=history_limit)
    task_text = (task or "").strip()
    if (
        task_text
        and histories
        and histories[-1].role == Role.USER
        and (histories[-1].content or "").strip() == task_text
    ):
        histories = histories[:-1]
    return ContextAssembler().assemble(
        system_prompt=system_prompt,
        histories=histories,
        current_task=task_text,
    )


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


def _skills_dir(cfg: HubloomConfig) -> Path:
    raw = (cfg.skills_dir or "skills").strip() or "skills"
    path = Path(raw)
    if not path.is_absolute():
        path = _ROOT / path
    return path


def build_think_system(
    cfg: HubloomConfig,
    mcp_setup: AgentMcpSetup | None,
) -> str:
    parts = [THINK_SYSTEM.strip()]
    skills = load_skills(_skills_dir(cfg), exclude=cfg.skills_exclude)
    skills_text = build_skills_prompt(skills).strip()
    if skills_text:
        parts.append(skills_text)
    if mcp_setup is not None:
        catalog_text = format_catalog_for_prompt(mcp_setup.catalog).strip()
        if catalog_text:
            parts.append(catalog_text)
    return "\n\n".join(parts)


def _print_tools(registry: ToolRegistry) -> None:
    defs = registry.list_definitions()
    print(f"【已装配 tools】共 {len(defs)} 个")
    for d in defs:
        params = (d.get("parameters") or {}).get("properties") or {}
        keys = ", ".join(params.keys()) if params else "(无参)"
        print(f"  • {d['name']}: {d.get('description', '')[:80]}")
        print(f"    参数: {keys}")


def _print_messages(messages: list[Message]) -> None:
    print("【装配后的 messages】")
    for i, m in enumerate(messages):
        preview = m.content if isinstance(m.content, str) else str(m.content)
        extra = ""
        if m.tool_calls:
            names = ", ".join(f"{tc.name}({tc.id})" for tc in m.tool_calls)
            extra = f" tool_calls=[{names}]"
        if m.tool_call_id:
            extra += f" tool_call_id={m.tool_call_id}"
        if m.name and m.role == Role.TOOL:
            extra += f" name={m.name}"
        print(f"  [{i}] {m.role.value}: {preview!r}{extra}")


async def _run_think(
    llm,
    messages: list[Message],
    *,
    tools: list[dict],
    label: str,
) -> ThinkDecision | None:
    print("=" * 60)
    print(f"【{label}】")
    _print_messages(messages)
    print("【思考过程】")
    decision: ThinkDecision | None = None
    saw_delta = False
    async for item in think(llm, messages, tools=tools):
        if isinstance(item, ThoughtDeltaEvent):
            saw_delta = True
            print(item.delta, end="", flush=True)
        elif isinstance(item, ErrorEvent):
            print(f"\n[error] {item.error}")
        elif isinstance(item, ThinkDecision):
            decision = item
            if saw_delta:
                print()
            elif not (decision.content or "").strip():
                print("（本轮无文字思考，仅有 tool_calls 或空）")
    print("-" * 60)
    print("【ThinkDecision】")
    if decision is None:
        print("  （未收到）")
        return None
    print("  content:", decision.content)
    print("  should_execute:", decision.should_execute)
    print("  should_respond:", decision.should_respond)
    print("  tool_calls:", decision.tool_calls)
    return decision


async def _run_execute(
    decision: ThinkDecision,
    runner: ToolRunner,
    memory: MemoryManager,
) -> ExecuteResult | None:
    print("=" * 60)
    print("【Execute】")
    result: ExecuteResult | None = None
    async for item in execute(
        decision.tool_calls,
        runner,
        think_content=decision.content,
    ):
        if isinstance(item, ToolCallEvent):
            print(f"  → call {item.tool_name} {item.args}")
        elif isinstance(item, ToolResultEvent):
            flag = "ERR" if item.is_error else "OK"
            preview = (item.result or "")[:500]
            print(f"  ← [{flag}] {item.tool_name}: {preview}")
        elif isinstance(item, ErrorEvent):
            print(f"  [error] {item.error}")
        elif isinstance(item, ExecuteResult):
            result = item

    if result is None:
        print("  （未收到 ExecuteResult）")
        return None

    for msg in result.messages:
        await save_message(memory, msg, source="agent")
    print(f"  已写入 conversation：{len(result.messages)} 条（ASSISTANT + TOOL）")
    await print_stored_conversation(memory, title="Execute 后库内会话")
    return result


async def _run_respond(
    llm,
    messages: list[Message],
    memory: MemoryManager,
) -> RespondResult | None:
    print("=" * 60)
    print("【Respond Markdown】")
    _print_messages(messages)
    print("【最终回复】")
    result: RespondResult | None = None
    async for item in respond(llm, messages, present_mode="markdown"):
        if isinstance(item, FinalAnswerDeltaEvent):
            print(item.delta, end="", flush=True)
        elif isinstance(item, ErrorEvent):
            print(f"\n[error] {item.error}")
        elif isinstance(item, FinalAnswerEvent):
            print()
            print("-" * 60)
            print("【FinalAnswerEvent】len=", len(item.content or ""))
        elif isinstance(item, RespondResult):
            result = item

    if result is None:
        print("  （未收到 RespondResult）")
        return None

    if (result.content or "").strip():
        await save_message(
            memory,
            Message(role=Role.ASSISTANT, content=result.content),
            source="agent",
        )
        print("  已写入 conversation：ASSISTANT 最终回复")
        await print_stored_conversation(memory, title="Respond 后库内会话")

    print("-" * 60)
    print("【RespondResult】")
    print("  present_mode:", result.present_mode)
    print("  content:", result.content)
    return result


async def test_respond() -> None:
    cfg = HubloomConfig.from_file(_ROOT / "config" / "env.yaml")
    if not (cfg.openai_api_key or "").strip():
        raise SystemExit("config/env.yaml 未配置 llm.api_key")

    llm = create_llm(
        api_key=cfg.openai_api_key,
        model=cfg.openai_model,
        base_url=cfg.openai_base_url,
    )

    # 固定 session，便于续跑与查库；可用环境变量 SESSION_ID 覆盖
    session_id = (os.getenv("SESSION_ID") or "").strip() or "test-respond-8390ec77"
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
    print(f"CLEAR_SESSION={_CLEAR_SESSION}")

    mcp_setup: AgentMcpSetup | None = None
    try:
        registry, mcp_setup = await load_tools(cfg, memory)
        runner = ToolRunner(registry)
        tool_defs = registry.list_definitions()
        think_system = build_think_system(cfg, mcp_setup)
        _print_tools(registry)
        print(f"skills_dir={_skills_dir(cfg)}")
        print(
            "skills:",
            [
                s["name"]
                for s in load_skills(_skills_dir(cfg), exclude=cfg.skills_exclude)
            ],
        )

        # 若库内已有历史，先展示（支持 SESSION_ID 续跑）
        existing = await load_histories(memory)
        if existing:
            await print_stored_conversation(memory, title="已有会话（续跑）")

        task = "帮我查一下当前的库存"
        await save_message(
            memory,
            Message(role=Role.USER, content=task),
            source="user",
        )
        await print_stored_conversation(memory, title="写入 USER 后")

        for round_i in range(1, _MAX_THINK_ROUNDS + 1):
            print()
            # 首轮：USER 已落库，assemble 去重后再拼 current_task
            # 后续：仅从库召回（含 tool 轨迹）
            task_arg = task if round_i == 1 else ""
            messages = await assemble_from_memory(
                memory,
                system_prompt=think_system,
                task=task_arg,
            )
            decision = await _run_think(
                llm,
                messages,
                tools=tool_defs,
                label=f"Think#{round_i}",
            )
            if decision is None:
                print("未收到 ThinkDecision，结束")
                return

            if decision.should_execute:
                print()
                exec_result = await _run_execute(decision, runner, memory)
                if exec_result is None:
                    return
                continue

            if decision.should_respond:
                print()
                # Respond：换 system，历史全部从 conversation 召回
                respond_messages = await assemble_from_memory(
                    memory,
                    system_prompt=RESPOND_MARKDOWN_SYSTEM.strip(),
                    task="",
                )
                await _run_respond(llm, respond_messages, memory)
                return

            print("既不 execute 也不 respond，结束")
            return

        print(f"达到 Think 轮次上限 {_MAX_THINK_ROUNDS}，未进入 Respond")
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
                "清理：CLEAR_SESSION=1 PYTHONPATH=src .venv/bin/python tests/test_respond.py"
            )


if __name__ == "__main__":
    from observability import setup_log

    setup_log()
    asyncio.run(test_respond())
