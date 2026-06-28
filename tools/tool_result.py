"""工具/API 结果封装：传输层事实 → 交给 LLM 解读（不替 LLM 判定业务成败）。"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class ToolTransportResult:
    """MCP/HTTP 传输层结果（不含业务语义判断）。"""

    tool_name: str
    arguments: dict[str, Any]
    transport_ok: bool
    http_status: int | None = None
    http_reason: str | None = None
    body: str = ""
    error: str | None = None

    def to_llm_text(self) -> str:
        """生成供 Plan 交付物 / ReplyComposer 使用的结构化文本。"""
        payload: dict[str, Any] = {
            "tool": self.tool_name,
            "arguments": self.arguments or {},
            "transport_ok": self.transport_ok,
        }
        if self.http_status is not None:
            payload["http_status"] = self.http_status
        if self.http_reason:
            payload["http_reason"] = self.http_reason

        if not self.transport_ok:
            payload["error"] = self.error or "工具调用失败"
            return json.dumps(payload, ensure_ascii=False, indent=2)

        body = (self.body or "").strip()
        if body:
            try:
                payload["body"] = json.loads(body)
            except json.JSONDecodeError:
                payload["body"] = body
        else:
            payload["body"] = None
            payload["note"] = (
                "HTTP 调用已成功，但响应体为空（常见于 204 No Content）。"
                "请结合用户意图与 http_status 判断是否完成，勿臆造未返回的数据。"
            )

        return json.dumps(payload, ensure_ascii=False, indent=2)


def build_transport_result(
    *,
    tool_name: str,
    arguments: dict[str, Any] | None,
    transport_ok: bool,
    http_status: int | None = None,
    http_reason: str | None = None,
    body: str = "",
    error: str | None = None,
) -> ToolTransportResult:
    return ToolTransportResult(
        tool_name=tool_name,
        arguments=dict(arguments or {}),
        transport_ok=transport_ok,
        http_status=http_status,
        http_reason=http_reason,
        body=body or "",
        error=error,
    )
