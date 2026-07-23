"""TurnStateStore 回合 / 人机等待规则。"""

from __future__ import annotations

import pytest

from agent.turn_state import (
    TurnStateStore,
    answer_parts_need_human,
)


def test_message_supersedes_waiting_form() -> None:
    """等待表单时用户改发消息：允许，并作废旧 run 绑定。"""
    store = TurnStateStore()
    sid = "s1"
    r1 = store.begin_run(sid)
    store.mark_waiting(sid, r1, kind="a2ui")
    assert store.get_pending(sid) is not None
    assert store.get_pending(sid).run_id == r1

    old = store.supersede_if_waiting(sid)
    assert old is not None
    assert old.run_id == r1
    assert old.status == "superseded_by_message"
    assert store.get_pending(sid) is None

    r2 = store.begin_run(sid)
    assert r2 != r1


def test_action_must_match_waiting_run_id() -> None:
    store = TurnStateStore()
    sid = "s1"
    rid = store.begin_run(sid)
    store.mark_waiting(sid, rid)

    with pytest.raises(ValueError, match="没有等待中"):
        store.validate_action("other", rid)

    with pytest.raises(ValueError, match="不一致"):
        store.validate_action(sid, "run-stale")

    ok = store.validate_action(sid, rid)
    assert ok.run_id == rid

    resolved = store.resolve_action(sid, rid, resolution="submit")
    assert resolved.status == "submit"
    assert store.get_pending(sid) is None


def test_cancel_resolves_waiting() -> None:
    store = TurnStateStore()
    sid = "s1"
    rid = store.begin_run(sid)
    store.mark_waiting(sid, rid)
    store.resolve_action(sid, rid, resolution="cancel")
    assert store.get_pending(sid) is None


def test_answer_parts_need_human() -> None:
    assert answer_parts_need_human([{"type": "text", "text": "hi"}]) is False
    assert answer_parts_need_human([{"type": "a2ui"}]) is True
    assert answer_parts_need_human(None) is False
