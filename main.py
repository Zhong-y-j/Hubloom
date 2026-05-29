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

from agents.app.bootstrap import build_hub
from agents.scripts.hub_io import run_repl, run_turn
from observability import setup_log


async def async_main() -> None:

    setup_log()

    hub = build_hub()

    await run_repl(hub)
    # run_turn(hub, "帮我起草一份解除劳动合同协议书")


def main() -> None:
    asyncio.run(async_main())


if __name__ == "__main__":
    main()
