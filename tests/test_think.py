"""手工跑 Think：正式会话落库 → 召回历史 → MCP/Tool 装配 → ContextAssembler → think。

用法（仓库根目录）::

    PYTHONPATH=src .venv/bin/python tests/test_think.py
"""

from __future__ import annotations

import asyncio
import uuid
from pathlib import Path

from agent.events import ErrorEvent, ThoughtDeltaEvent
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
    """正式装配：内置 tool +（可选）MCP 元工具 list_tools / call_tool。"""
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
    """THINK_SYSTEM + Skills 名片 +（有 MCP 时）API 分组目录。"""
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


async def _seed_conversation(
    memory: MemoryManager,
    turns: list[tuple[Role, str]],
) -> None:
    """按正式路径把历史写入 conversation 表。"""
    for role, content in turns:
        await memory.remember(
            memory_type="conversation",
            message=Message(role=role, content=content),
            source="test",
        )


async def assemble_think_context(
    memory: MemoryManager,
    *,
    task: str,
    system_prompt: str,
    history_limit: int = 20,
) -> list[Message]:
    """正式装配：召回会话历史 + system + 当前任务。"""
    recalled = await memory.recall(
        memory_type="conversation",
        top_k=history_limit,
    )
    histories = list(recalled.messages or [])

    # 若末条已是本轮 USER（与 task 相同），去掉以免 ContextAssembler 再拼一条
    task_text = (task or "").strip()
    if (
        histories
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
        print(f"  [{i}] {m.role.value}: {preview!r}")


async def _run_think(
    llm,
    messages: list[Message],
    *,
    tools: list[dict],
    label: str,
) -> ThinkDecision | None:
    print("=" * 60)
    print(f"【任务】{label}")
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


async def test_think() -> None:
    cfg = HubloomConfig.from_file(_ROOT / "config" / "env.yaml")
    if not (cfg.openai_api_key or "").strip():
        raise SystemExit("config/env.yaml 未配置 llm.api_key")

    llm = create_llm(
        api_key=cfg.openai_api_key,
        model=cfg.openai_model,
        base_url=cfg.openai_base_url,
    )

    # 独立 session，避免污染日常 memory.db 里的业务会话
    session_id = f"test-think-{uuid.uuid4().hex[:8]}"
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

        print()
        task2 = "帮我添加一个宠物"
        await memory.remember(
            memory_type="conversation",
            message=Message(role=Role.USER, content=task2),
            source="test",
        )
        messages2 = await assemble_think_context(
            memory,
            task=task2,
            system_prompt=system_prompt,
        )
        await _run_think(llm, messages2, tools=tool_defs, label=task2)
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
    asyncio.run(test_think())
