"""Experience Case schema 解析与序列化测试。

运行::

    PYTHONPATH=. uv run python -m memory.tests.test_experience_case
"""

from __future__ import annotations

from memory.experience_case import parse_batch_extraction


def test_parse_batch_extraction() -> None:
    payload = """
    ```json
    {
      "cases": [{
        "user_intent": "查订单",
        "approach": "先 list_orders 再 get_order",
        "tools_used": [{"name": "list_orders", "success": true}],
        "outcome": "success",
        "user_satisfied": "unknown",
        "lesson": "订单需先列表再详情"
      }],
      "semantic_rules": [{
        "rule": "订单类先 list 再 detail",
        "confidence": "high",
        "domain": "orders"
      }]
    }
    ```
    """
    result = parse_batch_extraction(payload)
    assert not result.skipped
    assert len(result.cases) == 1
    assert len(result.semantic_rules) == 1

    case = result.cases[0]
    assert "查订单" in case.to_episodic_content()
    assert case.to_episodic_metadata()["memory_kind"] == "experience_case"

    rule = result.semantic_rules[0]
    assert "订单" in rule.to_semantic_content()
    assert rule.to_semantic_metadata()["memory_kind"] == "semantic_rule"


if __name__ == "__main__":
    test_parse_batch_extraction()
    print("experience_case schema OK")
