"""人工测试：与 Agent 相同链路（原生元工具 → 单个全量 MCP）。

示例::

    PYTHONPATH=src uv run python -m mcp_adapter.test_mcp --list
    PYTHONPATH=src uv run python -m mcp_adapter.test_mcp --tools Banner
    PYTHONPATH=src uv run python -m mcp_adapter.test_mcp -i
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path
from typing import Any

SRC_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = SRC_ROOT.parent


def _pp(data: Any) -> str:
    if isinstance(data, str):
        try:
            parsed = json.loads(data)
            return json.dumps(parsed, ensure_ascii=False, indent=2)
        except json.JSONDecodeError:
            return data
    return json.dumps(data, ensure_ascii=False, indent=2)


def _parse_json_object(raw: str, *, label: str) -> dict[str, Any]:
    try:
        value = json.loads(raw or "{}")
    except json.JSONDecodeError as exc:
        raise SystemExit(f"无效的 {label} JSON: {exc}") from exc
    if not isinstance(value, dict):
        raise SystemExit(f"{label} 必须是 JSON 对象")
    return value


def _tool_map(bindings) -> dict[str, Any]:
    return {tool.name: tool for tool in bindings.tools}


async def _load_bindings():
    from hubloom.config import HubloomConfig
    from mcp_adapter.discovery import load_agent_mcp_bindings

    cfg = HubloomConfig.from_file(str(REPO_ROOT / "config" / "env.yaml"))
    swagger = (cfg.mcp_swagger_url or "").strip()
    if not swagger:
        raise SystemExit("config/env.yaml 未配置 mcp.swagger_url")

    child_env: dict[str, str] = {}
    if cfg.mcp_auth_scheme:
        child_env["MCP_AUTH_SCHEME"] = str(cfg.mcp_auth_scheme).strip()

    setup = await load_agent_mcp_bindings(
        swagger_url=swagger,
        base_url=cfg.mcp_base_url,
        env=child_env or None,
        cwd=str(SRC_ROOT),
    )
    return setup.bindings, setup.catalog


async def _run_meta(bindings, name: str, **kwargs: Any) -> str:
    tools = _tool_map(bindings)
    if name not in tools:
        raise SystemExit(f"元工具 {name!r} 不存在；当前有: {sorted(tools.keys())}")
    return await tools[name].execute(**kwargs)


async def cmd_list(bindings) -> None:
    print("=== Agent 可见的元工具（原生 Tool，非网关 MCP）===")
    for tool in bindings.tools:
        print(f"\n• {tool.name}")
        print(f"  {tool.description}")
        params = tool.parameters.get("properties", {})
        if params:
            print(f"  参数: {', '.join(params.keys())}")


async def cmd_groups(catalog) -> None:
    from mcp_adapter.gateway.catalog import format_catalog_for_prompt

    print("=== API 分组目录（来自 Swagger）===")
    print(format_catalog_for_prompt(catalog))


async def cmd_tools(bindings, tag: str) -> None:
    print(f"=== list_tools(tag={tag!r}) ===")
    text = await _run_meta(bindings, "list_tools", tag=tag)
    print(_pp(text))


async def cmd_call(
    bindings, tag: str, tool_name: str, arguments: dict[str, Any]
) -> None:
    print(f"=== call_tool(tag={tag!r}, tool_name={tool_name!r}) ===")
    print(f"arguments = {_pp(arguments)}")
    text = await _run_meta(
        bindings,
        "call_tool",
        tag=tag,
        tool_name=tool_name,
        arguments=arguments,
    )
    print("\n--- 结果 ---")
    print(_pp(text))


async def cmd_meta(bindings, name: str, arguments: dict[str, Any]) -> None:
    print(f"=== {name} ===")
    print(f"arguments = {_pp(arguments)}")
    text = await _run_meta(bindings, name, **arguments)
    print("\n--- 结果 ---")
    print(_pp(text))


async def cmd_smoke(
    bindings,
    catalog,
    *,
    tag: str,
    tool_name: str,
    tool_args: dict[str, Any],
) -> None:
    print("=== Smoke：元工具 → 全量 MCP ===\n")
    await cmd_list(bindings)
    print()
    await cmd_groups(catalog)
    print()
    await cmd_tools(bindings, tag)
    print()
    await cmd_call(bindings, tag, tool_name, tool_args)


async def cmd_interactive(bindings, catalog) -> None:
    tools = _tool_map(bindings)
    print("=== MCP 交互测试（Agent 同款元工具）===")
    print("可用元工具:", ", ".join(sorted(tools.keys())))
    print("输入 q 退出\n")

    while True:
        print("-" * 60)
        print("1) 打印 API 分组目录（Swagger）")
        print("2) list_tools <tag>")
        print("3) call_tool <tag> <tool_name> [json_args]")
        print("4) 任意元工具 <name> [json_kwargs]")
        print("q) 退出")
        line = input("\n> ").strip()
        if not line or line.lower() in {"q", "quit", "exit"}:
            break

        try:
            if line == "1":
                await cmd_groups(catalog)
                continue

            parts = line.split(maxsplit=1)
            cmd = parts[0]

            if cmd == "2":
                if len(parts) < 2:
                    print("用法: 2 <tag>")
                    continue
                await cmd_tools(bindings, parts[1].strip())
                continue

            if cmd == "3":
                tokens = (parts[1] if len(parts) > 1 else "").split()
                if len(tokens) < 2:
                    print('用法: 3 <tag> <tool_name> [{"k":"v"}]')
                    continue
                tag, tool_name = tokens[0], tokens[1]
                args = _parse_json_object(
                    tokens[2] if len(tokens) > 2 else "{}",
                    label="arguments",
                )
                await cmd_call(bindings, tag, tool_name, args)
                continue

            if cmd == "4":
                tokens = (parts[1] if len(parts) > 1 else "").split(maxsplit=1)
                if not tokens:
                    print("用法: 4 <meta_tool_name> [json_kwargs]")
                    continue
                name = tokens[0]
                kwargs = _parse_json_object(
                    tokens[1] if len(tokens) > 1 else "{}",
                    label="kwargs",
                )
                await cmd_meta(bindings, name, kwargs)
                continue

            print("未知命令，请输入 1 / 2 / 3 / 4 / q")
        except Exception as exc:
            print(f"错误: {exc}")


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="人工测试元工具 → 全量 MCP（与 HubloomAgent.create 同款）"
    )
    p.add_argument("-i", "--interactive", action="store_true", help="交互模式")
    p.add_argument("--list", action="store_true", help="列出元工具")
    p.add_argument("--groups", action="store_true", help="打印 API 分组目录（Swagger）")
    p.add_argument("--tools", metavar="TAG", help="调用 list_tools")
    p.add_argument(
        "--call",
        nargs=2,
        metavar=("TAG", "TOOL"),
        help="经 call_tool 调用后端工具，如: --call Banner Banner_GetList",
    )
    p.add_argument(
        "--meta",
        metavar="NAME",
        help="直接调用指定元工具，配合 --args",
    )
    p.add_argument(
        "--args",
        default="{}",
        help="JSON 参数；--call 时为后端工具参数；--meta 时为元工具 kwargs",
    )
    p.add_argument("--tag", default="Banner", help="smoke 默认 tag")
    p.add_argument(
        "--tool",
        default="Banner_GetList",
        help="smoke 默认后端工具名",
    )
    return p


async def main() -> int:
    parser = build_parser()
    args = parser.parse_args()

    print(f"src: {SRC_ROOT}")
    print("backend: python -m mcp_adapter.server.worker --full")
    print()

    bindings, catalog = await _load_bindings()
    try:
        if args.interactive:
            await cmd_interactive(bindings, catalog)
            return 0

        if args.list:
            await cmd_list(bindings)
            return 0

        if args.groups:
            await cmd_groups(catalog)
            return 0

        if args.tools:
            await cmd_tools(bindings, args.tools)
            return 0

        if args.call:
            tag, tool_name = args.call
            tool_args = _parse_json_object(args.args, label="arguments")
            await cmd_call(bindings, tag, tool_name, tool_args)
            return 0

        if args.meta:
            meta_args = _parse_json_object(args.args, label="kwargs")
            await cmd_meta(bindings, args.meta, meta_args)
            return 0

        tool_args = _parse_json_object(args.args, label="arguments")
        await cmd_smoke(
            bindings,
            catalog,
            tag=args.tag,
            tool_name=args.tool,
            tool_args=tool_args,
        )
        return 0
    finally:
        await bindings.client.close()
        print("\n=== MCP 连接已关闭 ===")


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
