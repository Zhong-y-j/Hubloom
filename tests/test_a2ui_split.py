"""A2UI 最终回复切分与流式过滤单元测试。"""

from __future__ import annotations

import json
import unittest

from agents.a2ui_split import (
    A2uiStreamSplitter,
    map_a2ui_events,
    parse_a2ui_payload,
    split_a2ui_reply,
)
from agents.events import (
    A2uiMessagesEvent,
    FinalAnswerDeltaEvent,
    FinalAnswerEvent,
    ThoughtDeltaEvent,
    ToolCallEvent,
)


_SAMPLE_MSGS = [
    {
        "version": "v0.9.1",
        "createSurface": {
            "surfaceId": "s1",
            "catalogId": "https://a2ui.org/specification/v0_9/catalogs/basic/catalog.json",
        },
    },
    {
        "version": "v0.9.1",
        "updateComponents": {
            "surfaceId": "s1",
            "components": [{"id": "root", "component": {"Text": {"text": "hi"}}}],
        },
    },
]


def _pack(md: str, delimiter: str = "---a2ui_JSON---") -> str:
    return f"{md}\n\n{delimiter}\n{json.dumps(_SAMPLE_MSGS, ensure_ascii=False)}\n"


class SplitA2uiReplyTests(unittest.TestCase):
    def test_no_delimiter(self) -> None:
        md, msgs, err = split_a2ui_reply("只是一段说明")
        self.assertEqual(md, "只是一段说明")
        self.assertIsNone(msgs)
        self.assertIsNone(err)

    def test_standard_split(self) -> None:
        md, msgs, err = split_a2ui_reply(_pack("请补充信息："))
        self.assertEqual(md, "请补充信息：")
        self.assertIsNone(err)
        self.assertEqual(len(msgs or []), 2)
        self.assertIn("createSurface", (msgs or [])[0])

    def test_four_dashes_delimiter(self) -> None:
        md, msgs, err = split_a2ui_reply(_pack("ok", "----a2ui_JSON----"))
        self.assertEqual(md, "ok")
        self.assertIsNone(err)
        self.assertIsNotNone(msgs)

    def test_fenced_json(self) -> None:
        raw = (
            "说明\n\n---a2ui_JSON---\n"
            f"```json\n{json.dumps(_SAMPLE_MSGS)}\n```\n"
        )
        md, msgs, err = split_a2ui_reply(raw)
        self.assertEqual(md, "说明")
        self.assertIsNone(err)
        self.assertEqual(len(msgs or []), 2)

    def test_invalid_json(self) -> None:
        md, msgs, err = split_a2ui_reply("x\n\n---a2ui_JSON---\n{not-json}\n")
        self.assertEqual(md, "x")
        self.assertIsNone(msgs)
        self.assertIsNotNone(err)

    def test_parse_rejects_non_array(self) -> None:
        msgs, err = parse_a2ui_payload('{"createSurface": {}}')
        self.assertIsNone(msgs)
        self.assertIn("array", err or "")


class StreamSplitterTests(unittest.TestCase):
    def test_streams_markdown_then_a2ui_event(self) -> None:
        full = _pack("好的，请补充：")
        splitter = A2uiStreamSplitter()
        deltas: list[str] = []

        mid = full.index("a2ui_JSON")
        chunk1 = full[: mid - 2]
        chunk2 = full[mid - 2 :]

        for part in (chunk1, chunk2):
            step = 7
            for i in range(0, len(part), step):
                deltas.extend(splitter.feed_delta(part[i : i + step]))

        finished = splitter.finish_final(full)
        types = [type(e).__name__ for e in finished]
        self.assertIn("A2uiMessagesEvent", types)
        self.assertIn("FinalAnswerEvent", types)

        streamed = "".join(deltas)
        self.assertNotIn("createSurface", streamed)

        catch_up = "".join(
            e.delta for e in finished if isinstance(e, FinalAnswerDeltaEvent)
        )
        final_md = next(e.content for e in finished if isinstance(e, FinalAnswerEvent))
        self.assertEqual((streamed + catch_up).rstrip(), final_md.rstrip())
        self.assertEqual(final_md, "好的，请补充：")

        a2ui = next(e for e in finished if isinstance(e, A2uiMessagesEvent))
        self.assertEqual(len(a2ui.messages), 2)

    def test_plain_markdown_flushes_hold(self) -> None:
        text = "你好，这是一段没有 A2UI 的回复。"
        splitter = A2uiStreamSplitter()
        deltas: list[str] = []
        for i in range(0, len(text), 3):
            deltas.extend(splitter.feed_delta(text[i : i + 3]))
        finished = splitter.finish_final(text)
        catch_up = "".join(
            e.delta for e in finished if isinstance(e, FinalAnswerDeltaEvent)
        )
        final = next(e.content for e in finished if isinstance(e, FinalAnswerEvent))
        self.assertEqual("".join(deltas) + catch_up, final)
        self.assertFalse(any(isinstance(e, A2uiMessagesEvent) for e in finished))


class MapA2uiEventsTests(unittest.IsolatedAsyncioTestCase):
    async def test_strips_a2ui_from_thought_and_salvages(self) -> None:
        thought = _pack("缺 name/address，正式回复用表单。")
        final_only = "要添加小区，请补充名称和地址。"

        async def source():
            step = 11
            for i in range(0, len(thought), step):
                yield ThoughtDeltaEvent(
                    phase="before_execute",
                    delta=thought[i : i + step],
                )
            yield ToolCallEvent(call_id="1", tool_name="list_tools", args={})
            yield FinalAnswerEvent(content=final_only)

        out = [ev async for ev in map_a2ui_events(source())]
        thought_text = "".join(
            e.delta for e in out if isinstance(e, ThoughtDeltaEvent)
        )
        self.assertNotIn("createSurface", thought_text)
        self.assertNotIn("---a2ui_JSON---", thought_text)
        self.assertIn("缺 name", thought_text)

        a2ui_events = [e for e in out if isinstance(e, A2uiMessagesEvent)]
        self.assertEqual(len(a2ui_events), 1)
        self.assertEqual(len(a2ui_events[0].messages), 2)

        finals = [e for e in out if isinstance(e, FinalAnswerEvent)]
        self.assertEqual(finals[-1].content, final_only)


class SseMappingTests(unittest.TestCase):
    def test_a2ui_sse_event_name(self) -> None:
        from agents.sse import event_to_sse

        name, payload = event_to_sse(A2uiMessagesEvent(messages=_SAMPLE_MSGS))
        self.assertEqual(name, "a2ui")
        self.assertEqual(payload["messages"], _SAMPLE_MSGS)


if __name__ == "__main__":
    unittest.main()
