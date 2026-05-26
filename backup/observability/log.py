"""灵枢日志：仅 Loguru，一个入口 + 一个写法。

用法::

    from observability import setup_log, log, logger

    setup_log(capture_print=True)   # 默认只写文件；终端要日志可 console=True

    log("进入 ReAct", phase="react", session="mem:xxx")
    log(query="我叫张三", hits=0)   # 只有字段也可以
    直接用 logger 时建议 logger.opt(depth=1).info(...) 才能对准调用处行号

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

# 文件日志含：相对路径、行号、函数名（便于定位代码）
_FILE_LOG_FORMAT = (
    "{time:YYYY-MM-DD HH:mm:ss} | {level: <7} | " "{extra[loc]} | {message}"
)
_CONSOLE_LOG_FORMAT = "{time:HH:mm:ss} | {level: <7} | {extra[loc]} | {message}"


def setup_log(
    file: str | Path | None = None,
    *,
    level: str | None = None,
    console: bool | None = None,
    capture_print: bool = False,
) -> Path:
    """配置日志：默认只写入 ``logs/agentcortex.log``（不在控制台重复打日志）。

    环境变量 ``CORTEX_LOG_CONSOLE=1`` 可重新打开终端日志输出。
    ``print`` 仍会显示在终端（与 ``capture_print`` 无关）。
    """
    path = Path(file or _LOG_FILE)
    path.parent.mkdir(parents=True, exist_ok=True)
    level = (level or "INFO").upper()

    def _patch_location(record: dict) -> None:
        file_path = Path(record["file"].path)
        try:
            rel = file_path.relative_to(Path.cwd())
        except ValueError:
            rel = file_path
        record["extra"]["loc"] = f"{rel}:{record['line']} in {record['function']}()"

    logger.configure(patcher=_patch_location)
    logger.remove()
    logger.add(
        path,
        level=level,
        rotation="10 MB",
        retention=5,
        encoding="utf-8",
        format=_FILE_LOG_FORMAT,
    )
    if console:
        logger.add(
            sys.stderr,
            level=level,
            colorize=True,
            format=_CONSOLE_LOG_FORMAT,
        )

    if capture_print:
        _hook_print()

    log("日志已启用", file=str(path.resolve()))
    return path.resolve()


def log(message: str = "", /, *, _depth: int = 1, **fields) -> None:
    """记一条日志：正文 + 任意关键字，传什么写什么。

    ``_depth`` 供内部使用（如捕获 print 时跳过包装层），一般无需传入。
    """
    parts: list[str] = []
    if message:
        parts.append(str(message))
    for key, value in fields.items():
        parts.append(f"{key}={value}")
    if parts:
        logger.opt(depth=_depth).info(" | ".join(parts))


def _hook_print() -> None:
    def patched_print(*args, **kwargs) -> None:
        _original_print(*args, **kwargs)
        if args:
            # depth=2：跳过 patched_print / log，定位到真正调用 print() 的代码行
            log("[print]", _depth=2, text=" ".join(str(a) for a in args))

    builtins.print = patched_print  # type: ignore[assignment]


def restore_print() -> None:
    builtins.print = _original_print
