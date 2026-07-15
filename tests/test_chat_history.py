"""对话历史展示辅助单元测试。"""

from __future__ import annotations

import unittest

from examples.chat.history import messages_for_display


class ChatHistoryTests(unittest.TestCase):
    def test_keeps_user_and_display_assistant(self) -> None:
        rows = [
            {
                "role": "user",
                "content": "你好",
                "created_at": "2026-06-28 10:00:00",
            },
            {
                "role": "assistant",
                "content": "你好！",
                "metadata_json": '{"route":"direct_reply"}',
                "created_at": "2026-06-28 10:00:01",
            },
            {
                "role": "assistant",
                "content": "中间进度（无展示元数据，应过滤）",
                "created_at": "2026-06-28 10:00:02",
            },
        ]
        messages = messages_for_display(rows)
        self.assertEqual(len(messages), 2)
        self.assertEqual(messages[0].role, "user")
        self.assertEqual(messages[1].content, "你好！")
        self.assertEqual(messages[1].route, "direct_reply")
        self.assertEqual(messages[1].created_at, "2026-06-28 10:00:01")

    def test_skips_empty_content(self) -> None:
        rows = [{"role": "assistant", "content": "   ", "created_at": None}]
        self.assertEqual(messages_for_display(rows), [])


if __name__ == "__main__":
    unittest.main()
