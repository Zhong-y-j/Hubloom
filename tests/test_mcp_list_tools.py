"""连接 MCP 并打印全部工具（最小联调）。

支持：

1. **http** — 连已启动的 Streamable HTTP MCP（见 ``test_mcp_serve_swagger.py``）
2. **stdio** — 本地拉起 Swagger worker（与 Runtime 默认路径一致）
3. **multi** — 同时连多路（示例：stdio 企业 API + 一个 HTTP URL）

用法（仓库根目录）::

    # 连 HTTP MCP
    PYTHONPATH=src .venv/bin/python tests/test_mcp_list_tools.py --url http://127.0.0.1:8001/mcp

    # 本地 stdio（读 config/env.yaml 的 swagger_url）
    PYTHONPATH=src .venv/bin/python tests/test_mcp_list_tools.py --stdio

    # 多路：stdio + 一个 HTTP
    PYTHONPATH=src .venv/bin/python tests/test_mcp_list_tools.py --multi --url http://127.0.0.1:8001/mcp
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from pathlib import Path

from config import HubloomConfig
from mcp_adapter.config.models import McpEndpoint
from mcp_adapter.discovery import (
    connect_full_mcp,
    connect_http_mcp,
    connect_mcp_endpoints,
)


def _config_path() -> Path:
    env = (os.environ.get("HUBLOOM_CONFIG") or "").strip()
    if env:
        return Path(env).expanduser().resolve()
    return Path("config/env.yaml").resolve()


def _load_cfg() -> HubloomConfig:
    path = _config_path()
    if not path.is_file():
        raise SystemExit(f"找不到配置文件: {path}")
    return HubloomConfig.from_file(path)


def _src_cwd() -> str:
    return str(Path(__file__).resolve().parents[1] / "src")


def _print_tools(tools: list[dict], *, limit: int | None) -> None:
    n = len(tools)
    print(f"tools: {n}")
    shown = tools if limit is None or limit <= 0 else tools[:limit]
    for t in shown:
        sid = t.get("server_id")
        prefix = f"[{sid}] " if sid else ""
        desc = (t.get("description") or "").replace("\n", " ").strip()
        if len(desc) > 80:
            desc = desc[:77] + "..."
        print(f"  - {prefix}{t.get('name')}: {desc}")
    if limit and limit > 0 and n > limit:
        print(f"  ... 另有 {n - limit} 个未显示（--limit 0 显示全部）")


async def cmd_http(*, url: str, headers_json: str | None, limit: int) -> None:
    headers = json.loads(headers_json) if headers_json else None
    client = await connect_http_mcp(url, headers=headers)
    try:
        tools = await client.list_tools()
        print(f"transport: http")
        print(f"url: {url}")
        _print_tools(tools, limit=limit)
    finally:
        await client.close()


async def cmd_stdio(*, limit: int) -> None:
    cfg = _load_cfg()
    swagger = (cfg.mcp_swagger_url or "").strip()
    if not swagger:
        raise SystemExit("mcp.swagger_url 未配置")
    child_env: dict[str, str] = {}
    if cfg.mcp_auth_scheme:
        child_env["MCP_AUTH_SCHEME"] = str(cfg.mcp_auth_scheme).strip()
    if cfg.mcp_token:
        child_env["MCP_TOKEN"] = str(cfg.mcp_token).strip()
    client = await connect_full_mcp(
        swagger_url=swagger,
        base_url=cfg.mcp_base_url,
        env=child_env or None,
        cwd=_src_cwd(),
    )
    try:
        tools = await client.list_tools()
        print("transport: stdio")
        print(f"swagger: {swagger}")
        _print_tools(tools, limit=limit)
    finally:
        await client.close()


async def cmd_multi(*, url: str, headers_json: str | None, limit: int) -> None:
    cfg = _load_cfg()
    swagger = (cfg.mcp_swagger_url or "").strip()
    if not swagger:
        raise SystemExit("mcp.swagger_url 未配置")
    headers = json.loads(headers_json) if headers_json else {}
    child_env: dict[str, str] = {}
    if cfg.mcp_auth_scheme:
        child_env["MCP_AUTH_SCHEME"] = str(cfg.mcp_auth_scheme).strip()
    if cfg.mcp_token:
        child_env["MCP_TOKEN"] = str(cfg.mcp_token).strip()

    endpoints = [
        McpEndpoint(
            id="enterprise",
            transport="stdio",
            swagger_url=swagger,
            base_url=cfg.mcp_base_url,
            env=child_env,
        ),
        McpEndpoint(
            id="remote",
            transport="http",
            url=url,
            headers=headers,
        ),
    ]
    registry = await connect_mcp_endpoints(endpoints, cwd=_src_cwd())
    try:
        tools = await registry.list_all_tools(prefix=True)
        print("transport: multi (enterprise=stdio, remote=http)")
        print(f"servers: {', '.join(registry.ids)}")
        _print_tools(tools, limit=limit)
    finally:
        await registry.close()


async def _main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="连接 MCP 并列出工具")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument(
        "--stdio",
        action="store_true",
        help="本地拉起 Swagger worker（默认若未给 --url）",
    )
    mode.add_argument(
        "--multi",
        action="store_true",
        help="stdio + --url 两路同时连",
    )
    parser.add_argument(
        "--url",
        default="",
        help="Streamable HTTP MCP URL，如 http://127.0.0.1:8001/mcp",
    )
    parser.add_argument(
        "--headers",
        default="",
        help='可选 JSON headers，如 \'{"Authorization":"Bearer x"}\'',
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=50,
        help="最多打印条数；0=全部",
    )
    args = parser.parse_args(argv)
    url = (args.url or "").strip()
    headers = (args.headers or "").strip() or None
    limit = args.limit

    if args.multi:
        if not url:
            raise SystemExit("--multi 需要 --url")
        await cmd_multi(url=url, headers_json=headers, limit=limit)
    elif url and not args.stdio:
        await cmd_http(url=url, headers_json=headers, limit=limit)
    else:
        await cmd_stdio(limit=limit)


if __name__ == "__main__":
    try:
        asyncio.run(_main())
    except KeyboardInterrupt:
        sys.exit(130)
