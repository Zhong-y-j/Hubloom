"""A2UI 工具数据绑定单元测试。"""

from __future__ import annotations

import json
import unittest

from agents.a2ui_bind import (
    bind_tool_data_to_a2ui_messages,
    resolve_dotted_path,
    resolve_tool_bind_value,
)


_TOOL_BODY = {
    "tool": "GatedCommunity_GetList",
    "arguments": {},
    "transport_ok": True,
    "body": {
        "totalCount": 2,
        "items": [
            {"id": "id-1", "name": "碧桂园", "address": "上海"},
            {"id": "id-2", "name": "测试小区", "address": "宁波"},
        ],
    },
}


class A2uiBindTests(unittest.TestCase):
    def test_resolve_dotted_path(self) -> None:
        self.assertEqual(
            len(resolve_dotted_path(_TOOL_BODY, "body.items")),
            2,
        )

    def test_resolve_object_sentinel(self) -> None:
        results = [("GatedCommunity_GetList", json.dumps(_TOOL_BODY), False)]
        value = {"$hubloom_tool": {"path": "body.items"}}
        resolved = resolve_tool_bind_value(value, results)
        self.assertEqual(resolved[0]["name"], "碧桂园")

    def test_resolve_string_sentinel(self) -> None:
        results = [("GetList", json.dumps(_TOOL_BODY), False)]
        resolved = resolve_tool_bind_value("$hubloom:body.items", results)
        self.assertEqual(len(resolved), 2)

    def test_bind_messages(self) -> None:
        results = [("GatedCommunity_GetList", json.dumps(_TOOL_BODY), False)]
        messages = [
            {
                "version": "v0.9.1",
                "updateDataModel": {
                    "surfaceId": "s1",
                    "path": "/items",
                    "value": {"$hubloom_tool": {"path": "body.items"}},
                },
            }
        ]
        bound = bind_tool_data_to_a2ui_messages(messages, results)
        self.assertEqual(bound[0]["updateDataModel"]["value"][1]["name"], "测试小区")
        # 原消息未被原地修改
        self.assertIn("$hubloom_tool", messages[0]["updateDataModel"]["value"])

    def test_tool_filter(self) -> None:
        other = {"body": {"items": [{"name": "wrong"}]}}
        results = [
            ("OtherTool", json.dumps(other), False),
            ("GatedCommunity_GetList", json.dumps(_TOOL_BODY), False),
        ]
        value = {
            "$hubloom_tool": {
                "tool": "GatedCommunity",
                "path": "body.items",
            }
        }
        resolved = resolve_tool_bind_value(value, results)
        self.assertEqual(resolved[0]["name"], "碧桂园")

    def test_normalize_list_path_and_missing_template(self) -> None:
        from agents.a2ui_bind import normalize_a2ui_messages

        messages = [
            {
                "version": "v0.9.1",
                "updateComponents": {
                    "surfaceId": "s1",
                    "components": [
                        {
                            "id": "root",
                            "component": "Column",
                            "children": ["list"],
                        },
                        {
                            "id": "list",
                            "component": "List",
                            "children": {
                                "componentId": "row",
                                "path": "/items",
                            },
                        },
                    ],
                },
            },
            {
                "version": "v0.9.1",
                "updateDataModel": {
                    "surfaceId": "s1",
                    "path": "/",
                    "value": [{"name": "A"}, {"name": "B"}],
                },
            },
        ]
        fixed = normalize_a2ui_messages(messages)
        udm = fixed[1]["updateDataModel"]
        self.assertEqual(udm["path"], "/items")
        self.assertEqual(udm["value"][0]["name"], "A")
        ids = {c["id"] for c in fixed[0]["updateComponents"]["components"]}
        self.assertIn("row", ids)
        self.assertIn("row__name", ids)
        self.assertIn("row__addr", ids)
        self.assertIn("row__status", ids)

    def test_upgrade_thin_name_only_template(self) -> None:
        from agents.a2ui_bind import normalize_a2ui_messages

        messages = [
            {
                "version": "v0.9.1",
                "updateComponents": {
                    "surfaceId": "s1",
                    "components": [
                        {
                            "id": "list",
                            "component": "List",
                            "children": {
                                "componentId": "communityItem",
                                "path": "/items",
                            },
                        },
                        {
                            "id": "communityItem",
                            "component": "Card",
                            "child": "communityItem__label",
                        },
                        {
                            "id": "communityItem__label",
                            "component": "Text",
                            "text": {"path": "name"},
                            "variant": "body",
                        },
                    ],
                },
            }
        ]
        fixed = normalize_a2ui_messages(messages)
        ids = {c["id"] for c in fixed[0]["updateComponents"]["components"]}
        self.assertIn("communityItem__addr", ids)
        self.assertNotIn("communityItem__label", ids)

    def test_unwrap_order_detail_and_relativize_row_paths(self) -> None:
        from agents.a2ui_bind import normalize_a2ui_messages

        messages = [
            {
                "version": "v0.9.1",
                "updateComponents": {
                    "surfaceId": "s1",
                    "components": [
                        {
                            "id": "status",
                            "component": "Text",
                            "text": {"path": "/status"},
                        },
                        {
                            "id": "paidTime",
                            "component": "Text",
                            "text": {
                                "call": "formatString",
                                "args": {"value": "支付时间：${/paidTime}"},
                            },
                        },
                        {
                            "id": "itemsList",
                            "component": "List",
                            "children": {
                                "componentId": "itemCard",
                                "path": "/orderItems",
                            },
                        },
                        {
                            "id": "itemCard",
                            "component": "Card",
                            "child": "itemPrice",
                        },
                        {
                            "id": "itemPrice",
                            "component": "Text",
                            "text": {
                                "call": "formatString",
                                "args": {"value": "单价：${/unitPrice} 元"},
                            },
                        },
                        {
                            "id": "remarksList",
                            "component": "List",
                            "children": {
                                "componentId": "remarkCard",
                                "path": "/orderRemarks",
                            },
                        },
                        {
                            "id": "remarkCard",
                            "component": "Text",
                            "text": {"path": "remark"},
                        },
                    ],
                },
            },
            {
                "version": "v0.9.1",
                "updateDataModel": {
                    "surfaceId": "s1",
                    "path": "/orderItems",
                    "value": [
                        {
                            "status": "Completed",
                            "paidTime": "2026-05-31T05:58:40Z",
                            "totalAmount": 0.08,
                            "orderItems": [
                                {"productName": "普洗", "unitPrice": 0.05, "quantity": 1}
                            ],
                            "orderRemarks": [{"type": "LicensePlateNumber", "remark": "浙BFFFFF"}],
                        }
                    ],
                },
            },
        ]
        fixed = normalize_a2ui_messages(messages)
        udm = fixed[1]["updateDataModel"]
        self.assertEqual(udm["path"], "/")
        self.assertIsInstance(udm["value"], dict)
        self.assertEqual(udm["value"]["status"], "Completed")
        self.assertEqual(len(udm["value"]["orderItems"]), 1)

        price = next(
            c
            for c in fixed[0]["updateComponents"]["components"]
            if c["id"] == "itemPrice"
        )
        self.assertEqual(
            price["text"]["args"]["value"],
            "单价：${unitPrice} 元",
        )
        # 根路径 formatString 保持绝对
        paid = next(
            c
            for c in fixed[0]["updateComponents"]["components"]
            if c["id"] == "paidTime"
        )
        self.assertIn("${/paidTime}", paid["text"]["args"]["value"])

    def test_upgrade_remark_urls_to_image(self) -> None:
        from agents.a2ui_bind import normalize_a2ui_messages

        url = "https://example.com/a.jpg"
        messages = [
            {
                "version": "v0.9.1",
                "updateComponents": {
                    "surfaceId": "s1",
                    "components": [
                        {
                            "id": "list",
                            "component": "List",
                            "children": {
                                "componentId": "row",
                                "path": "/orderRemarks",
                            },
                        },
                        {
                            "id": "row",
                            "component": "Column",
                            "children": ["rtype", "rtext"],
                        },
                        {
                            "id": "rtype",
                            "component": "Text",
                            "text": {"path": "type"},
                        },
                        {
                            "id": "rtext",
                            "component": "Text",
                            "text": {"path": "remark"},
                        },
                    ],
                },
            },
            {
                "version": "v0.9.1",
                "updateDataModel": {
                    "surfaceId": "s1",
                    "path": "/",
                    "value": {
                        "orderRemarks": [
                            {"type": "Snap", "remark": url},
                            {"type": "Snap", "remark": url.replace(".jpg", "2.jpg")},
                        ]
                    },
                },
            },
        ]
        fixed = normalize_a2ui_messages(messages)
        rtext = next(
            c
            for c in fixed[0]["updateComponents"]["components"]
            if c["id"] == "rtext"
        )
        self.assertEqual(rtext["component"], "Image")
        self.assertEqual(rtext["url"]["path"], "remark")


if __name__ == "__main__":
    unittest.main()
