"""模拟 Agent 会输出的 A2UI 消息（不调 LLM，纯示例）。

真实 Agent 在缺参 / 展示结果时，会流式推送类似的 JSON 数组。
格式对齐 A2UI v0.9.1 的 createSurface + updateComponents + updateDataModel。
"""

from __future__ import annotations

from typing import Any

# 与官方 @a2ui/lit basicCatalog.id 对齐（v0.9）
_CATALOG = "https://a2ui.org/specification/v0_9/catalogs/basic/catalog.json"


def _msg(payload: dict[str, Any]) -> dict[str, Any]:
    return {"version": "v0.9.1", **payload}


# ---------------------------------------------------------------------------
# 场景 1：预约表单（缺参补全）
# ---------------------------------------------------------------------------
BOOKING_FORM: list[dict[str, Any]] = [
    _msg(
        {
            "createSurface": {
                "surfaceId": "booking",
                "catalogId": _CATALOG,
            }
        }
    ),
    _msg(
        {
            "updateComponents": {
                "surfaceId": "booking",
                "components": [
                    {
                        "id": "root",
                        "component": "Column",
                        "children": ["title", "community", "plate", "date", "actions"],
                    },
                    {
                        "id": "title",
                        "component": "Text",
                        "text": "创建洗车预约",
                        "variant": "h2",
                    },
                    {
                        "id": "community",
                        "component": "TextField",
                        "label": "小区",
                        "value": {"path": "/booking/community"},
                    },
                    {
                        "id": "plate",
                        "component": "TextField",
                        "label": "车牌号",
                        "value": {"path": "/booking/plateNo"},
                    },
                    {
                        "id": "date",
                        "component": "TextField",
                        "label": "预约日期",
                        "value": {"path": "/booking/date"},
                    },
                    {
                        "id": "actions",
                        "component": "Row",
                        "children": ["submit-btn", "cancel-btn"],
                    },
                    {
                        "id": "submit-label",
                        "component": "Text",
                        "text": "确认预约",
                    },
                    {
                        "id": "submit-btn",
                        "component": "Button",
                        "child": "submit-label",
                        "variant": "primary",
                        "action": {"event": {"name": "confirm_booking"}},
                    },
                    {
                        "id": "cancel-label",
                        "component": "Text",
                        "text": "取消",
                    },
                    {
                        "id": "cancel-btn",
                        "component": "Button",
                        "child": "cancel-label",
                        "action": {"event": {"name": "cancel_booking"}},
                    },
                ],
            }
        }
    ),
    _msg(
        {
            "updateDataModel": {
                "surfaceId": "booking",
                "path": "/booking",
                "value": {
                    "community": "",
                    "plateNo": "",
                    "date": "2026-07-20",
                },
            }
        }
    ),
]


# ---------------------------------------------------------------------------
# 场景 2：确认卡片（写操作前二次确认）
# ---------------------------------------------------------------------------
CONFIRM_CARD: list[dict[str, Any]] = [
    _msg(
        {
            "createSurface": {
                "surfaceId": "confirm",
                "catalogId": _CATALOG,
            }
        }
    ),
    _msg(
        {
            "updateComponents": {
                "surfaceId": "confirm",
                "components": [
                    {
                        "id": "root",
                        "component": "Card",
                        "child": "body",
                    },
                    {
                        "id": "body",
                        "component": "Column",
                        "children": ["title", "summary", "actions"],
                    },
                    {
                        "id": "title",
                        "component": "Text",
                        "text": "确认取消订单？",
                        "variant": "h2",
                    },
                    {
                        "id": "summary",
                        "component": "Text",
                        "text": {"path": "/order/summary"},
                        "variant": "body",
                    },
                    {
                        "id": "actions",
                        "component": "Row",
                        "children": ["yes-btn", "no-btn"],
                    },
                    {
                        "id": "yes-label",
                        "component": "Text",
                        "text": "确认取消",
                    },
                    {
                        "id": "yes-btn",
                        "component": "Button",
                        "child": "yes-label",
                        "variant": "primary",
                        "action": {
                            "event": {
                                "name": "cancel_order",
                                "context": {"orderId": {"path": "/order/id"}},
                            }
                        },
                    },
                    {
                        "id": "no-label",
                        "component": "Text",
                        "text": "返回",
                    },
                    {
                        "id": "no-btn",
                        "component": "Button",
                        "child": "no-label",
                        "action": {"event": {"name": "dismiss"}},
                    },
                ],
            }
        }
    ),
    _msg(
        {
            "updateDataModel": {
                "surfaceId": "confirm",
                "path": "/order",
                "value": {
                    "id": "ORD-20260716-001",
                    "summary": "订单 ORD-20260716-001 · 阳光花园 · 粤B12345 · 明天 10:00",
                },
            }
        }
    ),
]


# ---------------------------------------------------------------------------
# 场景 3：结果列表（查询后展示）
# ---------------------------------------------------------------------------
ORDER_LIST: list[dict[str, Any]] = [
    _msg(
        {
            "createSurface": {
                "surfaceId": "orders",
                "catalogId": _CATALOG,
            }
        }
    ),
    _msg(
        {
            "updateComponents": {
                "surfaceId": "orders",
                "components": [
                    {
                        "id": "root",
                        "component": "Column",
                        "children": ["title", "item-0", "item-1"],
                    },
                    {
                        "id": "title",
                        "component": "Text",
                        "text": "最近预约",
                        "variant": "h2",
                    },
                    {
                        "id": "item-0",
                        "component": "Card",
                        "child": "item-0-body",
                    },
                    {
                        "id": "item-0-body",
                        "component": "Column",
                        "children": ["item-0-title", "item-0-desc"],
                    },
                    {
                        "id": "item-0-title",
                        "component": "Text",
                        "text": {"path": "/orders/0/title"},
                        "variant": "h3",
                    },
                    {
                        "id": "item-0-desc",
                        "component": "Text",
                        "text": {"path": "/orders/0/desc"},
                    },
                    {
                        "id": "item-1",
                        "component": "Card",
                        "child": "item-1-body",
                    },
                    {
                        "id": "item-1-body",
                        "component": "Column",
                        "children": ["item-1-title", "item-1-desc"],
                    },
                    {
                        "id": "item-1-title",
                        "component": "Text",
                        "text": {"path": "/orders/1/title"},
                        "variant": "h3",
                    },
                    {
                        "id": "item-1-desc",
                        "component": "Text",
                        "text": {"path": "/orders/1/desc"},
                    },
                ],
            }
        }
    ),
    _msg(
        {
            "updateDataModel": {
                "surfaceId": "orders",
                "path": "/orders",
                "value": [
                    {
                        "title": "ORD-001 · 待服务",
                        "desc": "阳光花园 · 粤B12345 · 明天 10:00",
                    },
                    {
                        "title": "ORD-002 · 已完成",
                        "desc": "翠湖苑 · 粤B88888 · 昨天 14:30",
                    },
                ],
            }
        }
    ),
]


SCENARIOS: dict[str, dict[str, Any]] = {
    "booking_form": {
        "id": "booking_form",
        "title": "预约表单",
        "user_says": "帮我预约洗车",
        "agent_says": "好的，请补充以下信息：",
        "why": "Agent 发现缺参，输出 A2UI 表单让用户填写，而不是一路追问。",
        "messages": BOOKING_FORM,
    },
    "confirm_card": {
        "id": "confirm_card",
        "title": "确认卡片",
        "user_says": "取消那个订单",
        "agent_says": "即将取消，请确认：",
        "why": "写操作前先出确认卡，用户点按钮后 Agent 再调 MCP。",
        "messages": CONFIRM_CARD,
    },
    "order_list": {
        "id": "order_list",
        "title": "结果列表",
        "user_says": "看看我最近的预约",
        "agent_says": "查到 2 条记录：",
        "why": "查询结果用卡片列表展示，比纯 Markdown 表格更可交互。",
        "messages": ORDER_LIST,
    },
}


def list_scenarios() -> list[dict[str, str]]:
    return [
        {
            "id": s["id"],
            "title": s["title"],
            "user_says": s["user_says"],
            "why": s["why"],
        }
        for s in SCENARIOS.values()
    ]


def get_scenario(scenario_id: str) -> dict[str, Any]:
    if scenario_id not in SCENARIOS:
        raise KeyError(scenario_id)
    return SCENARIOS[scenario_id]
