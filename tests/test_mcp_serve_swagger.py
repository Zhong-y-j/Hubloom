"""启动 Swagger → MCP 的独立 HTTP 服务（最小联调）。

从 ``config/env.yaml`` 读 ``mcp.swagger_url`` / ``mcp.base_url``，
以 Streamable HTTP 监听，供另一进程或容器客户端连接。

用法（仓库根目录）::

    PYTHONPATH=src .venv/bin/python tests/test_mcp_serve_swagger.py
    PYTHONPATH=src .venv/bin/python tests/test_mcp_serve_swagger.py --port 8001 --path /mcp

另开终端列工具::

    PYTHONPATH=src .venv/bin/python tests/test_mcp_list_tools.py --url http://127.0.0.1:8001/mcp

生产容器等价入口::

    PYTHONPATH=src MCP_SWAGGER_URL=... \\
      python -m mcp_adapter.server.worker --http --host 0.0.0.0 --port 8001
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
from pathlib import Path

from config import HubloomConfig
from mcp_adapter.config.models import McpServeConfig
from mcp_adapter.server.app import run_backend_http


def _config_path() -> Path:
    env = (os.environ.get("HUBLOOM_CONFIG") or "").strip()
    if env:
        return Path(env).expanduser().resolve()
    return Path("config/env.yaml").resolve()


def _inject_swagger_env() -> tuple[str, str | None]:
    path = _config_path()
    if not path.is_file():
        raise SystemExit(f"找不到配置文件: {path}")
    cfg = HubloomConfig.from_file(path)
    swagger = (cfg.mcp_swagger_url or "").strip()
    if not swagger:
        raise SystemExit(f"{path} 未配置 mcp.swagger_url")
    os.environ["MCP_SWAGGER_URL"] = swagger
    base = (cfg.mcp_base_url or "").strip() or None
    if base:
        os.environ["MCP_BASE_URL"] = base
    if cfg.mcp_auth_scheme:
        os.environ.setdefault("MCP_AUTH_SCHEME", str(cfg.mcp_auth_scheme).strip())
    return swagger, base


async def _main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Swagger → MCP HTTP 服务")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8001)
    parser.add_argument("--path", default="/mcp")
    parser.add_argument(
        "--stateful",
        action="store_true",
        help="有状态 HTTP（默认无状态）",
    )
    args = parser.parse_args(argv)

    swagger, base = _inject_swagger_env()
    url = f"http://{args.host}:{args.port}{args.path}"
    print(f"swagger: {swagger}")
    if base:
        print(f"base_url: {base}")
    print(f"listening: {url}")
    print("另开终端: PYTHONPATH=src .venv/bin/python tests/test_mcp_list_tools.py "
          f"--url {url}")

    await run_backend_http(
        McpServeConfig(
            host=args.host,
            port=args.port,
            path=args.path,
            stateless_http=not args.stateful,
            show_banner=False,
        )
    )


if __name__ == "__main__":
    try:
        asyncio.run(_main())
    except KeyboardInterrupt:
        sys.exit(0)
