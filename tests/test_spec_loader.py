"""mcp_adapter.spec_loader 单元测试。"""

from __future__ import annotations

import unittest

from mcp_adapter.spec_loader import dedupe_operation_ids, normalize_openapi_spec


class TestDedupeOperationIds(unittest.TestCase):
    def test_renames_duplicate_operation_ids(self) -> None:
        spec = {
            "swagger": "2.0",
            "paths": {
                "/api/system/user/export_data/": {
                    "get": {"operationId": "api_system_user_export_data"},
                },
                "/api/system/user/export/": {
                    "post": {"operationId": "api_system_user_export_data"},
                },
            },
        }
        dedupe_operation_ids(spec)
        self.assertEqual(
            spec["paths"]["/api/system/user/export_data/"]["get"]["operationId"],
            "api_system_user_export_data",
        )
        self.assertEqual(
            spec["paths"]["/api/system/user/export/"]["post"]["operationId"],
            "api_system_user_export_data_post",
        )

    def test_normalize_openapi3_dedupes_in_place(self) -> None:
        spec = {
            "openapi": "3.0.1",
            "paths": {
                "/a": {"get": {"operationId": "same_id"}},
                "/b": {"post": {"operationId": "same_id"}},
            },
        }
        result = normalize_openapi_spec(spec)
        self.assertEqual(
            result["paths"]["/b"]["post"]["operationId"],
            "same_id_post",
        )


if __name__ == "__main__":
    unittest.main()
