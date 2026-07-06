"""人工测试 MCP 网关 — 与 Agent bootstrap 使用相同链路。

启动方式（与 agents/app/bootstrap.py 一致）::

    uv run python mcp_adapter/server.py

本脚本通过 load_mcp_tools 连接网关，用 MCPTool.execute() 调用元工具。

示例::

    PYTHONPATH=. uv run python mcp_adapter/test_mcp.py
    PYTHONPATH=. uv run python mcp_adapter/test_mcp.py -i
    PYTHONPATH=. uv run python mcp_adapter/test_mcp.py --call pet getPetById --args '{"petId":1}'
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SERVER_SCRIPT = PROJECT_ROOT / "mcp_adapter" / "server.py"

# 与 bootstrap.py 相同的启动参数
DEFAULT_COMMAND = "uv"
DEFAULT_ARGS = ["run", "python", str(SERVER_SCRIPT)]


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
    from mcp_adapter import load_mcp_tools

    return await load_mcp_tools(
        command=DEFAULT_COMMAND,
        args=DEFAULT_ARGS,
        cwd=str(PROJECT_ROOT),
    )


async def _run_meta(bindings, name: str, **kwargs: Any) -> str:
    tools = _tool_map(bindings)
    if name not in tools:
        raise SystemExit(f"元工具 {name!r} 不存在；当前有: {sorted(tools.keys())}")
    return await tools[name].execute(**kwargs)


async def cmd_list(bindings) -> None:
    print("=== Agent 可见的 MCP 元工具 ===")
    for tool in bindings.tools:
        print(f"\n• {tool.name}")
        print(f"  {tool.description}")
        params = tool.parameters.get("properties", {})
        if params:
            print(f"  参数: {', '.join(params.keys())}")


async def cmd_groups(bindings) -> None:
    print("=== list_groups ===")
    text = await _run_meta(bindings, "list_groups")
    print(_pp(text))


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
    bindings, *, tag: str, tool_name: str, tool_args: dict[str, Any]
) -> None:
    print("=== Smoke：模拟 Agent 完整调用链 ===\n")

    await cmd_list(bindings)
    print()

    await cmd_groups(bindings)
    print()

    await cmd_tools(bindings, tag)
    print()

    await cmd_call(bindings, tag, tool_name, tool_args)


async def cmd_interactive(bindings) -> None:
    tools = _tool_map(bindings)
    print("=== MCP 交互测试（与 Agent 相同 MCPTool 链路）===")
    print("可用元工具:", ", ".join(sorted(tools.keys())))
    print("输入 q 退出\n")

    while True:
        print("-" * 60)
        print("1) list_groups")
        print("2) list_tools <tag>")
        print("3) call_tool <tag> <tool_name> [json_args]")
        print("4) 任意元工具 <name> [json_kwargs]")
        print("q) 退出")
        line = input("\n> ").strip()
        if not line or line.lower() in {"q", "quit", "exit"}:
            break

        try:
            if line == "1":
                await cmd_groups(bindings)
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
        description="人工测试 MCP 网关（Agent 同款 load_mcp_tools）"
    )
    p.add_argument("-i", "--interactive", action="store_true", help="交互模式")
    p.add_argument("--list", action="store_true", help="列出元工具")
    p.add_argument("--groups", action="store_true", help="调用 list_groups")
    p.add_argument("--tools", metavar="TAG", help="调用 list_tools")
    p.add_argument(
        "--call",
        nargs=2,
        metavar=("TAG", "TOOL"),
        help="经 call_tool 调用后端工具，如: --call pet getPetById",
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
    p.add_argument("--tag", default="pet", help="smoke 默认 tag（默认 pet）")
    p.add_argument(
        "--tool",
        default="getPetById",
        help="smoke 默认后端工具名（默认 getPetById）",
    )
    return p


async def main() -> int:
    load_dotenv(PROJECT_ROOT / ".env")

    if not SERVER_SCRIPT.is_file():
        print(f"找不到网关入口: {SERVER_SCRIPT}", file=sys.stderr)
        return 1

    parser = build_parser()
    args = parser.parse_args()

    print(f"项目根: {PROJECT_ROOT}")
    print(f"启动: {DEFAULT_COMMAND} {' '.join(DEFAULT_ARGS)}")
    print(
        f"MCP_SWAGGER_URL = {( __import__('os').getenv('MCP_SWAGGER_URL') or '(默认 Petstore)')}"
    )
    print(
        f"MCP_BASE_URL     = {( __import__('os').getenv('MCP_BASE_URL') or '(从 spec 推断)')}"
    )
    print()

    bindings = await _load_bindings()
    try:
        if args.interactive:
            await cmd_interactive(bindings)
            return 0

        if args.list:
            await cmd_list(bindings)
            return 0

        if args.groups:
            await cmd_groups(bindings)
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

        # 默认 smoke
        tool_args = _parse_json_object(args.args, label="arguments")
        if tool_args == {} and args.tool == "getPetById":
            tool_args = {"petId": 1}
        await cmd_smoke(
            bindings,
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
