"""全量 OpenAPI MCP 进程入口。

用法::

    # 本地 stdio（Runtime / connect_full_mcp 默认）
    PYTHONPATH=src MCP_SWAGGER_URL=... python -m mcp_adapter.server.worker --full

    # 独立 HTTP 服务（可单独容器部署）
    PYTHONPATH=src MCP_SWAGGER_URL=... \\
      python -m mcp_adapter.server.worker --http --host 0.0.0.0 --port 8001 --path /mcp

容器示例环境变量：``MCP_SWAGGER_URL``、可选 ``MCP_BASE_URL`` / ``MCP_AUTH_SCHEME`` / ``MCP_TOKEN``。
"""

from __future__ import annotations

import argparse
import asyncio
import sys

from mcp_adapter.config.models import McpServeConfig


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="python -m mcp_adapter.server.worker",
        description="Hubloom OpenAPI → MCP（stdio 或 HTTP）",
    )
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument(
        "--full",
        action="store_true",
        help="stdio 全量模式（默认；兼容旧调用）",
    )
    mode.add_argument(
        "--http",
        action="store_true",
        help="以 Streamable HTTP 独立监听（容器部署）",
    )
    parser.add_argument("--host", default="0.0.0.0", help="HTTP bind host")
    parser.add_argument("--port", type=int, default=8001, help="HTTP port")
    parser.add_argument("--path", default="/mcp", help="MCP HTTP path")
    parser.add_argument(
        "--stateful",
        action="store_true",
        help="HTTP 使用有状态会话（默认无状态，更利于并发）",
    )
    parser.add_argument(
        "--banner",
        action="store_true",
        help="打印 FastMCP banner",
    )
    # 兼容旧 argv：worker --full / worker full / 无参
    ns, unknown = parser.parse_known_args(argv)
    for token in unknown:
        t = token.strip()
        if t in ("--list",):
            continue
        if t in ("full", "*") and not ns.http:
            ns.full = True
            continue
        print(f"未知参数: {token}", file=sys.stderr)
        parser.print_help(sys.stderr)
        sys.exit(2)
    return ns


async def _main(argv: list[str] | None = None) -> None:
    from mcp_adapter.server.app import run_backend_http, run_backend_stdio

    args = _parse_args(argv)
    try:
        if args.http:
            cfg = McpServeConfig(
                host=args.host,
                port=args.port,
                path=args.path,
                stateless_http=not args.stateful,
                show_banner=args.banner,
            )
            await run_backend_http(cfg)
        else:
            await run_backend_stdio()
    except ValueError as exc:
        if "closed file" in str(exc).lower():
            return
        raise
    except OSError as exc:
        if getattr(exc, "errno", None) in {5, 9}:
            return
        raise


if __name__ == "__main__":
    asyncio.run(_main())
