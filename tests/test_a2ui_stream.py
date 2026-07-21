"""A2uiStreamSplitter：标签外流式文本 + 闭合块整包解析。"""

from __future__ import annotations

from agent.loop.a2ui_stream import A2uiStreamSplitter


def _feed_chunks(text: str, *, chunk: int = 7) -> tuple[str, list[dict]]:
    sp = A2uiStreamSplitter()
    texts: list[str] = []
    msgs: list[dict] = []
    for i in range(0, len(text), chunk):
        for em in sp.feed(text[i : i + chunk]):
            if em.kind == "text":
                texts.append(em.text)
            else:
                msgs.extend(em.messages)
    for em in sp.flush():
        if em.kind == "text":
            texts.append(em.text)
        else:
            msgs.extend(em.messages)
    return "".join(texts), msgs


def test_splitter_emits_text_without_tags():
    visible, msgs = _feed_chunks("你好，这是说明。\n\n后面还有一句。")
    assert "你好" in visible
    assert "<a2ui" not in visible
    assert msgs == []


def test_splitter_buffers_until_close_then_parses():
    raw = (
        "开场白\n"
        "<a2ui-json>\n"
        '{"version":"v0.9","createSurface":{"surfaceId":"s1","catalogId":"c"}}\n'
        "</a2ui-json>\n"
        "中间说明\n"
        "<a2ui-json>\n"
        '{"version":"v0.9","updateDataModel":{"surfaceId":"s1","value":{"a":1}}}\n'
        "</a2ui-json>\n"
        "收尾"
    )
    visible, msgs = _feed_chunks(raw, chunk=3)
    assert "开场白" in visible
    assert "中间说明" in visible
    assert "收尾" in visible
    assert "<a2ui-json>" not in visible
    assert len(msgs) == 2
    assert "createSurface" in msgs[0]
    assert "updateDataModel" in msgs[1]


def test_splitter_holds_partial_open_tag():
    sp = A2uiStreamSplitter()
    # 半截开标签不应泄漏
    out1 = sp.feed("前文<a2ui-j")
    assert all(e.kind == "text" for e in out1)
    assert "".join(e.text for e in out1 if e.kind == "text") == "前文"
    out2 = sp.feed(
        'son>\n{"version":"v0.9","createSurface":'
        '{"surfaceId":"x","catalogId":"c"}}\n</a2ui-json>尾'
    )
    texts = "".join(e.text for e in out2 if e.kind == "text")
    msgs = [m for e in out2 if e.kind == "a2ui" for m in e.messages]
    assert "createSurface" in msgs[0]
    assert "尾" in texts
    assert "<a2ui" not in texts
