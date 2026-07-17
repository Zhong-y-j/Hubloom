"""对话历史展示辅助单元测试。"""

from __future__ import annotations

import json
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

    def test_returns_a2ui_from_metadata(self) -> None:
        a2ui = [
            {
                "version": "v0.9.1",
                "createSurface": {
                    "surfaceId": "s1",
                    "catalogId": "https://a2ui.org/specification/v0_9/catalogs/basic/catalog.json",
                },
            }
        ]
        rows = [
            {
                "role": "assistant",
                "content": "（交互界面）",
                "metadata_json": json.dumps(
                    {"route": "thought", "a2ui": a2ui},
                    ensure_ascii=False,
                ),
                "created_at": "2026-07-17 12:00:00",
            }
        ]
        messages = messages_for_display(rows)
        self.assertEqual(len(messages), 1)
        self.assertEqual(messages[0].content, "（交互界面）")
        self.assertEqual(messages[0].a2ui, a2ui)


if __name__ == "__main__":
    unittest.main()
