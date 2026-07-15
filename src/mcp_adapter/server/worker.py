"""后端 MCP 子进程：全量或按 tag。

用法:
    PYTHONPATH=src uv run python -m mcp_adapter.server.worker --full
    PYTHONPATH=src uv run python -m mcp_adapter.server.worker user
"""

import asyncio
import sys


def _tag_from_argv() -> str | None:
    """返回 tag；``--full`` / ``full`` / ``*`` / 无参数 → 全量（None）。"""
    args = [a for a in sys.argv[1:] if a not in ("--list",)]
    if not args:
        return None
    first = args[0].strip()
    if not first or first in ("--full", "full", "*"):
        return None
    return first


async def _main() -> None:
    from mcp_adapter.server.app import run_backend_stdio

    tag = _tag_from_argv()
    try:
        await run_backend_stdio(tag=tag)
    except ValueError as exc:
        # 父进程关闭 stdin 后 FastMCP 可能在收尾时报 closed file，属正常退出噪音
        if "closed file" in str(exc).lower():
            return
        raise
    except OSError as exc:
        if getattr(exc, "errno", None) in {5, 9}:  # EIO / EBADF
            return
        raise


if __name__ == "__main__":
    asyncio.run(_main())


if __name__ == "__main__":
    asyncio.run(_main())
