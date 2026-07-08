"""Hubloom 日志（Loguru）。"""

from loguru import logger

from .log import log, setup_log

__all__ = ["setup_log", "log", "logger"]
