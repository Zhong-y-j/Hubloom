"""灵枢日志（Loguru）。"""

from loguru import logger

from .log import log, restore_print, setup_log

__all__ = ["setup_log", "log", "logger", "restore_print"]
