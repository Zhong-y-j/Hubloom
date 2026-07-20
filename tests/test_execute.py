"""手工跑 Think → Execute → 写回 → 再 Think。

用法（仓库根目录）::

    PYTHONPATH=src .venv/bin/python tests/test_execute.py
"""

from __future__ import annotations

import asyncio
import uuid
from pathlib import Path

from agent.events import (
    ErrorEvent,
    ThoughtDeltaEvent,
    ToolCallEvent,
    ToolResultEvent,
)
from agent.loop.execute import ExecuteResult, execute
from agent.loop.think import ThinkDecision, think
from agent.prompts import THINK_SYSTEM
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


def _db_path(cfg: HubloomConfig) -> str:
    raw = (cfg.memory_db_path or "data/memory.db").strip() or "data/memory.db"
    path = Path(raw)
    if not path.is_absolute():
        path = _ROOT / path
    path.parent.mkdir(parents=True, exist_ok=True)
    return str(path)


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


async def assemble_context(
    memory: MemoryManager,
    *,
    task: str = "",
    system_prompt: str,
    history_limit: int = 20,
) -> list[Message]:
    """召回历史 + system；``task=""`` 时不追加新 USER（工具后的第二轮 Think）。"""
    recalled = await memory.recall(memory_type="conversation", top_k=history_limit)
    histories = list(recalled.messages or [])
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
        await memory.remember(
            memory_type="conversation",
            message=msg,
            source="agent",
        )
    print(f"  已写回 {len(result.messages)} 条消息（ASSISTANT + TOOL）")
    return result


async def test_execute() -> None:
    cfg = HubloomConfig.from_file(_ROOT / "config" / "env.yaml")
    if not (cfg.openai_api_key or "").strip():
        raise SystemExit("config/env.yaml 未配置 llm.api_key")

    llm = create_llm(
        api_key=cfg.openai_api_key,
        model=cfg.openai_model,
        base_url=cfg.openai_base_url,
    )

    session_id = f"test-execute-{uuid.uuid4().hex[:8]}"
    memory = create_memory_manager(
        namespace=session_id,
        db_path=_db_path(cfg),
        vector_backend="none",
        graph_backend="none",
    )
    print(f"session_id={session_id}")
    print(f"memory_db={_db_path(cfg)}")

    mcp_setup: AgentMcpSetup | None = None
    try:
        registry, mcp_setup = await load_tools(cfg, memory)
        runner = ToolRunner(registry)
        tool_defs = registry.list_definitions()
        system_prompt = build_think_system(cfg, mcp_setup)
        _print_tools(registry)
        print(f"skills_dir={_skills_dir(cfg)}")
        print(
            "skills:",
            [
                s["name"]
                for s in load_skills(_skills_dir(cfg), exclude=cfg.skills_exclude)
            ],
        )

        # --- Think #1 ---
        print()
        task = "帮我添加一个宠物"
        await memory.remember(
            memory_type="conversation",
            message=Message(role=Role.USER, content=task),
            source="test",
        )
        messages1 = await assemble_context(
            memory, task=task, system_prompt=system_prompt
        )
        decision1 = await _run_think(
            llm, messages1, tools=tool_defs, label=f"Think#1 {task}"
        )
        if decision1 is None or not decision1.should_execute:
            print("Think#1 未发起 tool_calls，跳过 Execute")
            return

        # --- Execute ---
        print()
        exec_result = await _run_execute(decision1, runner, memory)
        if exec_result is None:
            return

        # --- Think #2 ---
        print()
        messages2 = await assemble_context(
            memory, task="", system_prompt=system_prompt
        )
        has_assistant_tools = any(
            m.role == Role.ASSISTANT and m.tool_calls for m in messages2
        )
        has_tool = any(m.role == Role.TOOL for m in messages2)
        print(
            f"【校验】第二轮含 assistant(tool_calls)={has_assistant_tools} "
            f"tool={has_tool}"
        )
        await _run_think(
            llm, messages2, tools=tool_defs, label="Think#2 after execute"
        )
    finally:
        if mcp_setup is not None:
            try:
                await mcp_setup.bindings.client.close()
                print("\n=== MCP 连接已关闭 ===")
            except Exception:
                pass
        try:
            await memory.clear_all(memory_type="conversation")
        except Exception:
            pass


if __name__ == "__main__":
    from observability import setup_log

    setup_log()
    asyncio.run(test_execute())
