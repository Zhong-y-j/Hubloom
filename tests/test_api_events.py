import unittest

from agents.core.events import (
    HubTurnCompleteEvent,
    TextDeltaEvent,
    ToolCallEvent,
)
from agents.api.events import event_to_sse, format_sse


class ApiEventsTests(unittest.TestCase):
    def test_text_delta(self) -> None:
        name, payload = event_to_sse(TextDeltaEvent(delta="你好"))
        self.assertEqual(name, "text_delta")
        self.assertEqual(payload["delta"], "你好")

    def test_turn_complete(self) -> None:
        name, payload = event_to_sse(
            HubTurnCompleteEvent(
                route="direct_reply",
                user_reply="ok",
                final_user_message="最终结果",
            )
        )
        self.assertEqual(name, "turn_complete")
        self.assertEqual(payload["final_message"], "最终结果")

    def test_format_sse(self) -> None:
        chunk = format_sse("text_delta", {"delta": "x"})
        self.assertIn("event: text_delta", chunk)
        self.assertIn('"delta": "x"', chunk)


if __name__ == "__main__":
    unittest.main()
