"""A2UI JSON 弯引号修复：避免 payload_fixer 把 “” 改成 ASCII " 截断字符串。"""

from __future__ import annotations

from agent.loop.a2ui_stream import neutralize_smart_quotes, parse_a2ui_json_block


def test_neutralize_smart_quotes_keeps_json_valid() -> None:
    # 模拟 LLM 在文案里用弯引号强调「禁用」
    raw = (
        '{\n'
        '  "version": "v0.9",\n'
        '  "updateComponents": {\n'
        '    "surfaceId": "s1",\n'
        '    "components": [\n'
        '      {"id": "root", "component": "Text", "text": "请用“禁用”代替删除"}\n'
        "    ]\n"
        "  }\n"
        "}"
    )
    # 官方 fixer 的 smart-quote 归一化会弄坏；我们先中和
    fixed = neutralize_smart_quotes(raw)
    assert "“" not in fixed and "”" not in fixed
    assert "「禁用」" in fixed
    msgs = parse_a2ui_json_block(raw, stage="test")
    assert len(msgs) == 1
    assert msgs[0]["updateComponents"]["components"][0]["text"] == "请用「禁用」代替删除"


def test_parse_plain_ascii_json_still_works() -> None:
    raw = '{"version":"v0.9","createSurface":{"surfaceId":"x","catalogId":"c"}}'
    msgs = parse_a2ui_json_block(raw, stage="test")
    assert msgs[0]["createSurface"]["surfaceId"] == "x"
