"""answer_display_parts：正文与 A2UI 交错拆分。"""

from __future__ import annotations

from agent.loop.respond import answer_display_parts, user_visible_content


def test_answer_parts_interleave_text_around_a2ui() -> None:
    raw = (
        "表单前说明。\n"
        "<a2ui-json>\n"
        '{"version":"v0.9","createSurface":{"surfaceId":"s1","catalogId":"c"}}\n'
        "</a2ui-json>\n"
        "请在上方界面中选择。"
    )
    parts = answer_display_parts(raw, a2ui_messages=[{"x": 1}])
    assert [p["type"] for p in parts] == ["text", "a2ui", "text"]
    assert "表单前" in parts[0]["text"]
    assert "上方界面" in parts[2]["text"]
    # content 列仍合并，不含标签
    visible = user_visible_content(raw, a2ui_messages=[{"x": 1}])
    assert "<a2ui-json>" not in visible
    assert "表单前" in visible and "上方界面" in visible


def test_answer_parts_single_a2ui_marker_for_three_blocks() -> None:
    raw = (
        "前文\n"
        "<a2ui-json>{\"version\":\"v0.9\",\"createSurface\":{\"surfaceId\":\"s\",\"catalogId\":\"c\"}}</a2ui-json>\n"
        "<a2ui-json>{\"version\":\"v0.9\",\"updateComponents\":{\"surfaceId\":\"s\",\"components\":[]}}</a2ui-json>\n"
        "<a2ui-json>{\"version\":\"v0.9\",\"updateDataModel\":{\"surfaceId\":\"s\",\"path\":\"/\",\"value\":{}}}</a2ui-json>\n"
        "后文"
    )
    parts = answer_display_parts(raw, a2ui_messages=[{}, {}, {}])
    assert [p["type"] for p in parts] == ["text", "a2ui", "text"]
