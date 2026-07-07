"""MCPTool 参数规范化单元测试。"""

from __future__ import annotations

import unittest

from tools.builtin.mcp_tool import _coerce_nested_arguments


class TestCoerceNestedArguments(unittest.TestCase):
    def test_parses_string_arguments_for_call_tool(self) -> None:
        payload = {
            "tag": "role",
            "tool_name": "api_system_role_create",
            "arguments": '{"name": "编辑员", "key": "editor"}',
        }
        out = _coerce_nested_arguments("call_tool", payload)
        self.assertEqual(out["arguments"], {"name": "编辑员", "key": "editor"})

    def test_leaves_dict_arguments_unchanged(self) -> None:
        payload = {
            "tag": "role",
            "tool_name": "api_system_role_create",
            "arguments": {"name": "编辑员", "key": "editor"},
        }
        out = _coerce_nested_arguments("call_tool", payload)
        self.assertEqual(out["arguments"], {"name": "编辑员", "key": "editor"})

    def test_ignores_other_tools(self) -> None:
        payload = {"arguments": '{"x": 1}'}
        out = _coerce_nested_arguments("list_tools", payload)
        self.assertEqual(out["arguments"], '{"x": 1}')


if __name__ == "__main__":
    unittest.main()
