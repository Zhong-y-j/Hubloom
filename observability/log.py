from __future__ import annotations

import builtins
import os
import sys
import traceback
from pathlib import Path

from loguru import logger

_original_print = builtins.print
_original_excepthook = sys.excepthook
_LOG_FILE = Path(os.getenv("CORTEX_LOG_FILE", "logs/debug.log"))

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
    log_uncaught: bool = True,
) -> Path:
    """配置日志：默认只写入 ``logs/debug.log``（不在控制台重复打日志）。

    - ``log_uncaught=True``：未捕获异常（如 NameError）写入日志并保留终端 traceback
    - ``capture_print``：``print`` 内容写入日志；终端仍显示 print
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
    if log_uncaught:
        _hook_uncaught_exceptions()

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


def _hook_uncaught_exceptions() -> None:
    """未捕获异常：写入日志文件，终端仍由默认 excepthook 打印 traceback。"""

    def _log_excepthook(
        exc_type: type[BaseException],
        exc_value: BaseException,
        exc_traceback,
    ) -> None:
        if issubclass(exc_type, KeyboardInterrupt):
            _original_excepthook(exc_type, exc_value, exc_traceback)
            return
        tb = "".join(
            traceback.format_exception(exc_type, exc_value, exc_traceback)
        ).strip()
        logger.error(
            "error | type={} | msg={}\n{}",
            exc_type.__name__,
            exc_value,
            tb,
        )
        _original_excepthook(exc_type, exc_value, exc_traceback)

    sys.excepthook = _log_excepthook
