"""离线记忆 worker CLI：定量提炼 + Qdrant 淘汰。

用法::

    # 扫描全部 session：满 N 轮 USER 则提炼，并执行 TTL/容量淘汰
    PYTHONPATH=. uv run python -m memory.run_worker

    # 只处理单个 session
    PYTHONPATH=. uv run python -m memory.run_worker --session mem:tester_id:default

    # 仅淘汰（cron 定时清理由现有 lifecycle 策略执行）
    PYTHONPATH=. uv run python -m memory.run_worker --maintain-only

    # 仅提炼，不淘汰
    PYTHONPATH=. uv run python -m memory.run_worker --consolidate-only

配置：``config/env.yaml``（``--config`` 可覆盖），不读 CORTEX_* 环境变量。
"""

from __future__ import annotations

import argparse
import asyncio

from core.factory import create_llm
from hubloom.config import HubloomConfig
from memory.memory_worker import MemoryMaintenanceWorker, WorkerConfig
from observability import setup_log


async def _async_main(args: argparse.Namespace) -> None:
    setup_log()
    cfg = HubloomConfig.from_file(args.config)
    worker_cfg = WorkerConfig.from_hubloom_config(cfg)
    llm = create_llm(
        api_key=worker_cfg.openai_api_key,
        model=worker_cfg.openai_model,
        base_url=worker_cfg.openai_base_url,
    )
    worker = MemoryMaintenanceWorker(llm, config=worker_cfg)
    try:
        result = await worker.run_once(
            session_id=args.session,
            consolidate=not args.maintain_only,
            maintain=not args.consolidate_only,
        )
    finally:
        await worker.close()

    print("--- memory worker ---")
    print("sessions_scanned:", result.sessions_scanned)
    print("sessions_consolidated:", result.sessions_consolidated)
    print("turns_processed:", result.turns_processed)
    print("cases_written:", result.cases_written)
    print("rules_written:", result.rules_written)
    print("evicted:", result.evicted)
    for item in result.session_results:
        if item.consolidated or item.pending_turns > 0:
            print(
                f"  session={item.session_id!r} "
                f"pending_turns={item.pending_turns} "
                f"consolidated={item.consolidated}"
            )
    if result.errors:
        print("errors:")
        for err in result.errors:
            print(" ", err)


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Hubloom 离线记忆 worker")
    parser.add_argument(
        "--config",
        default="config/env.yaml",
        help="Hubloom YAML 配置路径（默认 config/env.yaml）",
    )
    parser.add_argument(
        "--session",
        help="只处理指定 session_id / namespace（默认扫描全部）",
    )
    parser.add_argument(
        "--maintain-only",
        action="store_true",
        help="仅执行 Qdrant TTL/容量淘汰",
    )
    parser.add_argument(
        "--consolidate-only",
        action="store_true",
        help="仅执行批量提炼，不淘汰",
    )
    return parser.parse_args()


def main() -> None:
    args = _parse_args()
    if args.maintain_only and args.consolidate_only:
        raise SystemExit("不能同时指定 --maintain-only 与 --consolidate-only")
    asyncio.run(_async_main(args))


if __name__ == "__main__":
    main()
