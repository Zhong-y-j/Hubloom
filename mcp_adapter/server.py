"""MCP 网关启动入口（Agent 通过 stdio 连接此进程）。"""

from __future__ import annotations

import asyncio
import os
import sys


def _maybe_setup_log() -> None:
    if os.getenv("CORTEX_AGENT_LOG", "").lower() not in (
        "1",
        "true",
        "yes",
    ) and os.getenv("CORTEX_MCP_LOG", "").lower() not in ("1", "true", "yes"):
        return
    try:
        from observability import setup_log

        setup_log()
    except ModuleNotFoundError:
        pass


async def _main() -> None:
    from mcp_adapter.gateway.app import run_gateway

    await run_gateway()


if __name__ == "__main__":
    _maybe_setup_log()
    asyncio.run(_main())
