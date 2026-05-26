"""灵枢日志：仅 Loguru，一个入口 + 一个写法。

用法::

    from observability import setup_log, log, logger

    setup_log(capture_print=True)   # 程序启动时调一次

    log("进入 ReAct", phase="react", session="mem:xxx")
    log(query="我叫张三", hits=0)   # 只有字段也可以
    logger.info("直接用 loguru 也行")

测试::

    PYTHONPATH=. uv run python -m observability.test_log_demo
"""

from __future__ import annotations

import builtins
import os
import sys
from pathlib import Path

from loguru import logger

_original_print = builtins.print
_LOG_FILE = Path(os.getenv("CORTEX_LOG_FILE", "logs/agentcortex.log"))


def setup_log(
    file: str | Path | None = None,
    *,
    level: str | None = None,
    console: bool = True,
    capture_print: bool = False,
) -> Path:
    """配置日志：默认写入 ``logs/agentcortex.log``，可选终端与捕获 print。"""
    path = Path(file or _LOG_FILE)
    path.parent.mkdir(parents=True, exist_ok=True)
    level = (level or os.getenv("CORTEX_LOG_LEVEL", "INFO")).upper()

    logger.remove()
    logger.add(
        path,
        level=level,
        rotation="10 MB",
        retention=5,
        encoding="utf-8",
        format="{time:YYYY-MM-DD HH:mm:ss} | {level: <7} | {message}",
    )
    if console:
        logger.add(
            sys.stderr,
            level=level,
            colorize=True,
            format="{time:HH:mm:ss} | {level: <7} | {message}",
        )

    if capture_print or os.getenv("CORTEX_LOG_CAPTURE_PRINT", "").lower() in (
        "1",
        "true",
        "yes",
    ):
        _hook_print()

    log("日志已启用", file=str(path.resolve()))
    return path.resolve()


def log(message: str = "", /, **fields) -> None:
    """记一条日志：正文 + 任意关键字，传什么写什么。"""
    parts: list[str] = []
    if message:
        parts.append(str(message))
    for key, value in fields.items():
        parts.append(f"{key}={value}")
    if parts:
        logger.info(" | ".join(parts))


def _hook_print() -> None:
    def patched_print(*args, **kwargs) -> None:
        _original_print(*args, **kwargs)
        if args:
            log("[print]", text=" ".join(str(a) for a in args))

    builtins.print = patched_print  # type: ignore[assignment]


def restore_print() -> None:
    builtins.print = _original_print
