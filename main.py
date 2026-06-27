#!/usr/bin/env python3
"""Agent Cortex（灵枢）主入口。

PYTHONPATH=. python main.py
PYTHONPATH=. python main.py --repl
"""

from __future__ import annotations

import argparse
import asyncio
import os
import warnings

from agents.app.bootstrap import build_hub_async
from agents.scripts.hub_io import run_repl, run_turn
from observability import setup_log


async def async_main() -> None:

    setup_log()

    hub = await build_hub_async()
    try:
        await run_repl(hub)
        # await run_turn(hub, "帮我查一下宠物店的库存")
    finally:
        await hub.close()


def main() -> None:
    asyncio.run(async_main())


if __name__ == "__main__":
    main()
