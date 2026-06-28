"""工具/HTTP 传输层错误：是否可重试、提取用户可读业务消息。"""

from __future__ import annotations

import re

_NON_RETRYABLE_HTTP = frozenset({400, 401, 403, 404, 405, 409, 422, 451})
_RETRYABLE_HTTP = frozenset({408, 429, 500, 502, 503, 504})

_HTTP_STATUS_RE = re.compile(r"HTTP error (\d{3})", re.IGNORECASE)
_MESSAGE_RE = re.compile(
    r"""['"]message['"]\s*:\s*['"]([^'"]+)['"]""",
)


def extract_business_message(error_text: str) -> str | None:
    """从 MCP/HTTP 错误字符串中提取 API 返回的 message 字段。"""
    text = (error_text or "").strip()
    if not text:
        return None
    match = _MESSAGE_RE.search(text)
    if match:
        msg = match.group(1).strip()
        return msg or None
    return None


def http_status_from_error(error_text: str) -> int | None:
    match = _HTTP_STATUS_RE.search(error_text or "")
    if not match:
        return None
    try:
        return int(match.group(1))
    except ValueError:
        return None


def is_retryable_tool_error(error_text: str) -> bool:
    """4xx 业务/客户端错误不重试；5xx/429/408 等可重试。"""
    text = (error_text or "").strip()
    if not text:
        return False

    status = http_status_from_error(text)
    if status is not None:
        if status in _NON_RETRYABLE_HTTP:
            return False
        if status in _RETRYABLE_HTTP:
            return True
        if 400 <= status < 500:
            return False
        if status >= 500:
            return True

    # 已解析出明确业务 message 且含 Forbidden/错误码 → 不重试
    if extract_business_message(text) and status in (403, 400, 404, 422):
        return False

    return False


def format_step_failure(error_text: str, *, tool_name: str = "") -> str:
    """格式化为 deliverable 中的失败步骤说明。"""
    biz = extract_business_message(error_text)
    status = http_status_from_error(error_text)
    prefix = f"工具 {tool_name} 调用失败" if tool_name else "步骤执行失败"
    if biz:
        line = f"{prefix}：{biz}"
    else:
        line = f"{prefix}：{(error_text or '').strip()}"
    if status is not None:
        line += f"（HTTP {status}）"
    return line
