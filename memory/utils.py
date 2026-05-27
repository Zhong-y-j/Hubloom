from __future__ import annotations

import hashlib
from datetime import datetime, timedelta


def now_local_str() -> str:
    """返回本地时间字符串（无时区、非 UTC、非 timestamp）。

    格式：YYYY-MM-DD HH:MM:SS（可用于 SQLite TEXT 排序）
    """

    return datetime.now().replace(microsecond=0).strftime("%Y-%m-%d %H:%M:%S")


_LOCAL_FMT = "%Y-%m-%d %H:%M:%S"


def content_hash(text: str) -> str:
    """对正文做稳定哈希，用于去重与索引（SHA256 前 32 位 hex）。"""
    normalized = (text or "").strip()
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()[:32]


def subtract_days_local_str(current_time_str: str, days: int) -> str:
    """从本地时间字符串减去若干天，仍返回 ``YYYY-MM-DD HH:MM:SS``（可与 SQLite TEXT 排序一致）。"""

    dt = datetime.strptime(current_time_str, _LOCAL_FMT) - timedelta(days=days)
    return dt.strftime(_LOCAL_FMT)
