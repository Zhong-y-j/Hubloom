import unittest

from agents.events import TextDeltaEvent, ToolCallEvent
from agents.api.events import event_to_sse, format_sse, turn_complete_payload


class ApiEventsTests(unittest.TestCase):
    def test_text_delta(self) -> None:
        name, payload = event_to_sse(TextDeltaEvent(delta="你好"))
        self.assertEqual(name, "text_delta")
        self.assertEqual(payload["delta"], "你好")

    def test_turn_complete(self) -> None:
        name, payload = turn_complete_payload(
            route="direct_reply",
            final_message="最终结果",
            session_id="mem:tester:default",
        )
        self.assertEqual(name, "turn_complete")
        self.assertEqual(payload["final_message"], "最终结果")

    def test_tool_call_display_name(self) -> None:
        name, payload = event_to_sse(
            ToolCallEvent(
                call_id="1",
                tool_name="call_tool",
                args={"tool_name": "getOrderById", "tag": "store"},
            )
        )
        self.assertEqual(name, "tool_call")
        self.assertEqual(payload["tool_name"], "getOrderById")

    def test_format_sse(self) -> None:
        chunk = format_sse("text_delta", {"delta": "x"})
        self.assertIn("event: text_delta", chunk)
        self.assertIn('"delta": "x"', chunk)


if __name__ == "__main__":
    unittest.main()
