"""mcp_adapter.response_normalize 单元测试。"""

from __future__ import annotations

import unittest

from mcp_adapter.response_normalize import drf_pagination_from_envelope


class TestDrfPaginationFromEnvelope(unittest.TestCase):
    def test_dvadmin_dept_list(self) -> None:
        payload = {
            "code": 2000,
            "page": 1,
            "limit": 1,
            "total": 1,
            "data": [{"id": 1, "name": "DVAdmin团队"}],
            "msg": "success",
        }
        out = drf_pagination_from_envelope(payload)
        assert out is not None
        self.assertEqual(out["count"], 1)
        self.assertEqual(len(out["results"]), 1)
        self.assertEqual(out["results"][0]["name"], "DVAdmin团队")

    def test_already_drf(self) -> None:
        payload = {"count": 2, "results": [{"name": "a"}], "next": None}
        self.assertIsNone(drf_pagination_from_envelope(payload))


if __name__ == "__main__":
    unittest.main()
