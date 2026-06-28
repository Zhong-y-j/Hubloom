"""对话历史展示辅助单元测试。"""

from __future__ import annotations

import unittest

from agents.api.history import messages_for_display


class ChatHistoryTests(unittest.TestCase):
    def test_strips_intent_from_assistant(self) -> None:
        rows = [
            {
                "role": "user",
                "content": "你好",
                "created_at": "2026-06-28 10:00:00",
            },
            {
                "role": "assistant",
                "content": "你好！\n```intent\n{\"intent\":\"general_chat\"}\n```",
                "created_at": "2026-06-28 10:00:01",
            },
        ]
        messages = messages_for_display(rows)
        self.assertEqual(len(messages), 2)
        self.assertEqual(messages[0].role, "user")
        self.assertEqual(messages[1].content, "你好！")
        self.assertEqual(messages[1].created_at, "2026-06-28 10:00:01")

    def test_skips_empty_content(self) -> None:
        rows = [{"role": "assistant", "content": "   ", "created_at": None}]
        self.assertEqual(messages_for_display(rows), [])


if __name__ == "__main__":
    unittest.main()
