"""全量 OpenAPI MCP 子进程入口。

用法::

    PYTHONPATH=src MCP_SWAGGER_URL=... uv run python -m mcp_adapter.server.worker --full
"""

from __future__ import annotations

import asyncio
import sys


async def _main() -> None:
    from mcp_adapter.server.app import run_backend_stdio

    # 兼容旧调用 ``worker --full`` / 无参；不再支持按 tag 启动子进程
    args = [a for a in sys.argv[1:] if a not in ("--list",)]
    if args and args[0].strip() and args[0].strip() not in ("--full", "full", "*"):
        print(
            "mcp_adapter.server.worker 仅支持全量模式（--full）。"
            "按 tag 启动已移除；请用 Agent 元工具 list_tools(tag=...)。",
            file=sys.stderr,
        )
        sys.exit(2)

    try:
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
