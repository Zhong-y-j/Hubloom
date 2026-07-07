"""thought 鉴权阻断逻辑单元测试。"""

from __future__ import annotations

import json
import unittest

from agents.adp import Thought, is_login_related_tool, is_unauthenticated_tool_result


class TestAuthDetection(unittest.TestCase):
    def test_detects_dvadmin_auth_message(self) -> None:
        payload = {
            "tool": "api_system_area_list",
            "transport_ok": True,
            "http_status": 200,
            "body": {"code": 4000, "data": None, "msg": "身份认证信息未提供。"},
        }
        self.assertTrue(is_unauthenticated_tool_result(json.dumps(payload, ensure_ascii=False)))

    def test_detects_http_401(self) -> None:
        payload = {
            "tool": "api_system_area_list",
            "transport_ok": True,
            "http_status": 401,
            "body": {"detail": "Unauthorized"},
        }
        self.assertTrue(is_unauthenticated_tool_result(json.dumps(payload)))

    def test_ignores_unrelated_business_error(self) -> None:
        payload = {
            "tool": "api_system_area_list",
            "transport_ok": True,
            "http_status": 200,
            "body": {"code": 4000, "msg": "记录不存在"},
        }
        self.assertFalse(is_unauthenticated_tool_result(json.dumps(payload, ensure_ascii=False)))

    def test_login_related_tools(self) -> None:
        self.assertTrue(is_login_related_tool("captcha_get"))
        self.assertTrue(is_login_related_tool("api_login_create"))
        self.assertTrue(is_login_related_tool("api_token_create"))
        self.assertFalse(is_login_related_tool("api_system_area_list"))


class TestShouldReplan(unittest.TestCase):
    def test_skips_replan_when_auth_blocked(self) -> None:
        thought = Thought(llm=object())  # type: ignore[arg-type]
        thought._execute_had_errors = True
        thought._auth_failure_detected = True
        self.assertFalse(thought.should_replan("查询地区"))


if __name__ == "__main__":
    unittest.main()
