"""A2UI 最终回复切分与流式过滤单元测试。"""

from __future__ import annotations

import json
import unittest

from agents.a2ui_split import (
    A2uiStreamSplitter,
    extract_a2ui_messages,
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
            "components": [
                {"id": "root", "component": "Text", "text": "**hi**", "variant": "body"}
            ],
        },
    },
]


def _pack_legacy(md: str, delimiter: str = "---a2ui_JSON---") -> str:
    return f"{md}\n\n{delimiter}\n{json.dumps(_SAMPLE_MSGS, ensure_ascii=False)}\n"


def _pack_tags(*msgs: dict) -> str:
    parts = []
    for m in msgs:
        parts.append(f"<a2ui-json>\n{json.dumps(m, ensure_ascii=False)}\n</a2ui-json>")
    return "\n".join(parts)


class SplitA2uiReplyTests(unittest.TestCase):
    def test_no_delimiter(self) -> None:
        md, msgs, err = split_a2ui_reply("只是一段说明")
        self.assertEqual(md, "只是一段说明")
        self.assertIsNone(msgs)
        self.assertIsNone(err)

    def test_legacy_delimiter_split(self) -> None:
        md, msgs, err = split_a2ui_reply(_pack_legacy("请补充信息："))
        self.assertEqual(md, "请补充信息：")
        self.assertIsNone(err)
        self.assertEqual(len(msgs or []), 2)
        self.assertIn("createSurface", (msgs or [])[0])

    def test_official_a2ui_json_tags(self) -> None:
        raw = _pack_tags(_SAMPLE_MSGS[0], _SAMPLE_MSGS[1])
        md, msgs, err = extract_a2ui_messages(raw)
        self.assertEqual(md, "")
        self.assertIsNone(err)
        self.assertEqual(len(msgs or []), 2)

    def test_version_v09_normalized(self) -> None:
        msg = {
            "version": "v0.9",
            "createSurface": {
                "surfaceId": "s",
                "catalogId": "https://a2ui.org/specification/v0_9/catalogs/basic/catalog.json",
            },
        }
        raw = f"<a2ui-json>{json.dumps(msg)}</a2ui-json>"
        _, msgs, err = extract_a2ui_messages(raw)
        self.assertIsNone(err)
        self.assertEqual((msgs or [])[0]["version"], "v0.9.1")

    def test_four_dashes_delimiter(self) -> None:
        md, msgs, err = split_a2ui_reply(_pack_legacy("ok", "----a2ui_JSON----"))
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

    def test_parse_accepts_single_object(self) -> None:
        msgs, err = parse_a2ui_payload(
            json.dumps(
                {
                    "version": "v0.9.1",
                    "createSurface": {
                        "surfaceId": "s",
                        "catalogId": "c",
                    },
                }
            )
        )
        self.assertIsNone(err)
        self.assertEqual(len(msgs or []), 1)


class StreamSplitterTests(unittest.TestCase):
    def test_streams_markdown_then_a2ui_event_legacy(self) -> None:
        full = _pack_legacy("好的，请补充：")
        splitter = A2uiStreamSplitter()
        deltas: list[str] = []

        mid = full.index("a2ui_JSON")
        chunk1 = full[: mid - 2]
        chunk2 = full[mid - 2 :]

        for part in (chunk1, chunk2):
            step = 7
            for i in range(0, len(part), step):
                deltas.extend(splitter.feed_delta(part[i : i + step]))
                # delimiter 模式不中途 drain
                self.assertEqual(splitter.drain_completed_a2ui(), [])

        finished = splitter.finish_final(full)
        types = [type(e).__name__ for e in finished]
        self.assertIn("A2uiMessagesEvent", types)
        self.assertIn("FinalAnswerEvent", types)

        streamed = "".join(deltas)
        self.assertNotIn("createSurface", streamed)

        a2ui = next(e for e in finished if isinstance(e, A2uiMessagesEvent))
        self.assertEqual(len(a2ui.messages), 2)
        self.assertTrue(a2ui.replace)
        final_md = next(e.content for e in finished if isinstance(e, FinalAnswerEvent))
        # 有 A2UI 时最终文案为空（纯 A2UI 设计）
        self.assertEqual(final_md, "")

    def test_pure_tags_progressive_drain(self) -> None:
        """每闭合一个 </a2ui-json> 即可 drain 出消息。"""
        full = _pack_tags(_SAMPLE_MSGS[0], _SAMPLE_MSGS[1])
        splitter = A2uiStreamSplitter()
        progressive: list[dict] = []
        for i in range(0, len(full), 9):
            splitter.feed_delta(full[i : i + 9])
            progressive.extend(splitter.drain_completed_a2ui())

        self.assertEqual(len(progressive), 2)
        self.assertIn("createSurface", progressive[0])
        self.assertIn("updateComponents", progressive[1])
        self.assertEqual(splitter.streamed_count, 2)

        finished = splitter.finish_final(full)
        a2ui = next(e for e in finished if isinstance(e, A2uiMessagesEvent))
        self.assertTrue(a2ui.replace)
        self.assertEqual(len(a2ui.messages), 2)
        final_md = next(e.content for e in finished if isinstance(e, FinalAnswerEvent))
        self.assertEqual(final_md, "")

    def test_array_inside_one_tag_streams_objects(self) -> None:
        """单标签内 JSON 数组：对象完整即可中途 drain（不必等 </a2ui-json>）。"""
        inner = json.dumps(_SAMPLE_MSGS, ensure_ascii=False)
        full = f"<a2ui-json>\n{inner}\n</a2ui-json>"
        splitter = A2uiStreamSplitter()
        progressive: list[dict] = []
        # 喂到第一个对象结束之后、第二个尚未写完
        first_obj = json.dumps(_SAMPLE_MSGS[0], ensure_ascii=False)
        prefix = f"<a2ui-json>\n[{first_obj},"
        for i in range(0, len(prefix), 5):
            splitter.feed_delta(prefix[i : i + 5])
            progressive.extend(splitter.drain_completed_a2ui())
        self.assertEqual(len(progressive), 1)
        self.assertIn("createSurface", progressive[0])

        rest = full[len(prefix) :]
        for i in range(0, len(rest), 5):
            splitter.feed_delta(rest[i : i + 5])
            progressive.extend(splitter.drain_completed_a2ui())
        self.assertGreaterEqual(len(progressive), 2)
        self.assertIn("updateComponents", progressive[1])

    def test_pure_tags_no_markdown_final(self) -> None:
        full = _pack_tags(_SAMPLE_MSGS[0], _SAMPLE_MSGS[1])
        splitter = A2uiStreamSplitter()
        for i in range(0, len(full), 9):
            splitter.feed_delta(full[i : i + 9])
        finished = splitter.finish_final(full)
        self.assertTrue(any(isinstance(e, A2uiMessagesEvent) for e in finished))
        final_md = next(e.content for e in finished if isinstance(e, FinalAnswerEvent))
        self.assertEqual(final_md, "")

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
        thought = _pack_legacy("缺 name/address，正式回复用表单。")
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
        self.assertTrue(a2ui_events[0].replace)

        finals = [e for e in out if isinstance(e, FinalAnswerEvent)]
        # 从思考 salvage 出 A2UI 时，最终文案清空
        self.assertEqual(finals[-1].content, "")

    async def test_progressive_a2ui_during_final_deltas(self) -> None:
        full = _pack_tags(_SAMPLE_MSGS[0], _SAMPLE_MSGS[1])

        async def source():
            step = 13
            for i in range(0, len(full), step):
                yield FinalAnswerDeltaEvent(delta=full[i : i + step])
            yield FinalAnswerEvent(content=full)

        out = [ev async for ev in map_a2ui_events(source())]
        a2ui_events = [e for e in out if isinstance(e, A2uiMessagesEvent)]
        # 流式追加若干次 + 最终 replace 一次
        appends = [e for e in a2ui_events if not e.replace]
        replaces = [e for e in a2ui_events if e.replace]
        self.assertGreaterEqual(len(appends), 1)
        self.assertEqual(sum(len(e.messages) for e in appends), 2)
        self.assertEqual(len(replaces), 1)
        self.assertEqual(len(replaces[0].messages), 2)


class SseMappingTests(unittest.TestCase):
    def test_a2ui_sse_event_name(self) -> None:
        from agents.sse import event_to_sse

        name, payload = event_to_sse(A2uiMessagesEvent(messages=_SAMPLE_MSGS))
        self.assertEqual(name, "a2ui")
        self.assertEqual(payload["messages"], _SAMPLE_MSGS)
        self.assertNotIn("replace", payload)

    def test_a2ui_sse_replace_flag(self) -> None:
        from agents.sse import event_to_sse

        name, payload = event_to_sse(
            A2uiMessagesEvent(messages=_SAMPLE_MSGS, replace=True)
        )
        self.assertEqual(name, "a2ui")
        self.assertTrue(payload["replace"])


if __name__ == "__main__":
    unittest.main()
