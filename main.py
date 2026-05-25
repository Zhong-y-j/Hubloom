#!/usr/bin/env python3
"""Agent Cortex（灵枢）主入口。

默认运行完整 Hub 链路（ReAct → PlanExecute → Reflection）。

示例：
    PYTHONPATH=. python main.py
    PYTHONPATH=. python main.py --repl
    PYTHONPATH=. python main.py "帮我起草一份解除劳动合同协议书"
    RUN_REFLECTION=0 PYTHONPATH=. python main.py

阶段调试（可选）：
    PYTHONPATH=. python -m agents.scripts.react_demo
    PYTHONPATH=. python -m agents.scripts.plan_demo
    PYTHONPATH=. python -m agents.scripts.reflection_demo
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
import warnings

from agents.app.bootstrap import DEFAULT_QUERY, build_hub
from agents.scripts.hub_io import run_repl, run_turn

warnings.filterwarnings(
    "ignore",
    message="Failed to obtain server version",
    category=UserWarning,
)


def _env_run_reflection() -> bool:
    return os.getenv("RUN_REFLECTION", "1").lower() not in ("0", "false", "no")


async def async_main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        description="Agent Cortex（灵枢）— ReAct → PlanExecute → Reflection",
    )
    parser.add_argument(
        "--repl",
        action="store_true",
        help="多轮对话（同一 session，澄清后自动 Plan）",
    )
    parser.add_argument(
        "--no-reflection",
        action="store_true",
        help="跳过 Reflection 审查阶段",
    )
    parser.add_argument(
        "query",
        nargs="?",
        default=DEFAULT_QUERY,
        help="单轮用户输入（默认示例为软件开发合同需求）",
    )
    args = parser.parse_args(argv)

    run_reflection = _env_run_reflection() and not args.no_reflection
    hub = build_hub(run_reflection=run_reflection)

    if args.repl:
        await run_repl(hub)
    else:
        await run_turn(hub, args.query)


def main() -> None:
    asyncio.run(async_main())


if __name__ == "__main__":
    main()
