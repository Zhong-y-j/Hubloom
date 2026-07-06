"""单个 tag 后端 MCP 子进程（仅网关 spawn，Agent 不连）。

用法:
    PYTHONPATH=. uv run python -m mcp_adapter.server.worker user
    PYTHONPATH=. uv run python -m mcp_adapter.server.worker dictionary
"""

import asyncio
import sys


def _tag_from_argv() -> str | None:
    args = [a for a in sys.argv[1:]]
    if not args:
        return None
    return args[0].strip() or None


async def _main() -> None:
    from mcp_adapter.server.app import run_backend_stdio

    tag = _tag_from_argv()

    if tag is None:
        print(
            "用法: python -m mcp_adapter.server.worker <tag> [--list]", file=sys.stderr
        )
        sys.exit(1)

    await run_backend_stdio(tag=tag)


if __name__ == "__main__":
    asyncio.run(_main())
