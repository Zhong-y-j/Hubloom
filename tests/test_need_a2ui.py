"""Present NEED_A2UI 解析与 auto 路由。"""

from __future__ import annotations

from agent.loop.present import parse_need_a2ui
from agent.run import plan_respond_passes, resolve_respond_mode


def test_parse_need_a2ui_yes_no() -> None:
    assert parse_need_a2ui("NEED_A2UI: yes") is True
    assert parse_need_a2ui("NEED_A2UI: no") is False
    assert parse_need_a2ui("缺 name，交 Respond\nNEED_A2UI: yes") is True
    assert parse_need_a2ui("没有标记") is None


def test_parse_need_a2ui_inline_tolerance() -> None:
    assert parse_need_a2ui("我认为 NEED_A2UI: yes 比较合适") is True


def test_resolve_respond_mode_auto() -> None:
    assert resolve_respond_mode("auto", True) == "a2ui"
    assert resolve_respond_mode("auto", False) == "markdown"
    assert resolve_respond_mode("auto", None) == "markdown"
    assert resolve_respond_mode("a2ui", False) == "a2ui"
    assert resolve_respond_mode("markdown", True) == "markdown"


def test_plan_respond_passes_auto_dual() -> None:
    both = plan_respond_passes("auto", True)
    assert both.run_markdown is True and both.run_a2ui is True
    assert both.result_present_mode == "auto"

    md_only = plan_respond_passes("auto", False)
    assert md_only.run_markdown is True and md_only.run_a2ui is False

    force_a2ui = plan_respond_passes("a2ui", False)
    assert force_a2ui.run_markdown is False and force_a2ui.run_a2ui is True

    force_md = plan_respond_passes("markdown", True)
    assert force_md.run_markdown is True and force_md.run_a2ui is False
