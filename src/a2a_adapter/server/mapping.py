"""把 A2A 的 Message / 回复，和普通字符串互相转换。

现在：
- 进来：Message → 文本
- 出去：文本 → Artifact 的 parts

以后可能加（业务需要时再写）：
- 空消息 / 只有附件没有文字
- 多 Part 入站（文字 + 文件等）
- 非纯文本出站（JSON、文件等）
- 一次任务多个 Artifact / 多个 Part
- 流式中间结果（仍是文本 → Part，只是调用更勤）

不管：Task 状态、add_artifact、凭证、session、Cortex（那些在 executor / bridge）。
"""

from __future__ import annotations

from a2a.helpers import get_message_text, new_text_part
from a2a.types import Message, Part


def message_to_text(message: Message | None) -> str:
    """从 A2A Message 取出纯文本；没有则返回空串。"""
    if message is None:
        return ""
    return (get_message_text(message) or "").strip()


def text_to_artifact_parts(text: str) -> list[Part]:
    """把回复字符串打成 Artifact 需要的 parts。"""
    body = (text or "").strip() or "(empty)"
    return [new_text_part(text=body, media_type="text/plain")]


if __name__ == "__main__":
    from a2a.helpers import new_text_message
    from a2a.types import Role

    msg = new_text_message("查一下合同", role=Role.ROLE_USER)
    query = message_to_text(msg)
    print("message_to_text ->", repr(query))

    parts = text_to_artifact_parts(f"Echo: {query}")
    print("text_to_artifact_parts ->", parts)
