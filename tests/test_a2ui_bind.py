"""TextField 字面量 value 自动改写成 path 绑定。"""

from __future__ import annotations

from agent.loop.a2ui_bind import bind_editable_field_paths
from agent.loop.a2ui_stream import parse_a2ui_json_block


def test_bind_literal_textfield_from_checks_and_id():
    messages = [
        {
            "version": "v0.9",
            "updateComponents": {
                "surfaceId": "gated-community-create",
                "components": [
                    {
                        "id": "nameField",
                        "component": "TextField",
                        "label": "小区名称",
                        "value": "",
                        "checks": [
                            {
                                "condition": {
                                    "call": "required",
                                    "args": {"value": {"path": "/name"}},
                                },
                                "message": "必填",
                            }
                        ],
                    },
                    {
                        "id": "provinceField",
                        "component": "TextField",
                        "label": "省份",
                        "value": "",
                    },
                    {
                        "id": "addressField",
                        "component": "TextField",
                        "value": {"path": "/address"},
                    },
                ],
            },
        },
        {
            "version": "v0.9",
            "updateDataModel": {
                "surfaceId": "gated-community-create",
                "value": {
                    "name": "",
                    "address": "",
                    "province": "",
                },
            },
        },
    ]
    out = bind_editable_field_paths(messages)
    comps = out[0]["updateComponents"]["components"]
    assert comps[0]["value"] == {"path": "/name"}
    assert comps[1]["value"] == {"path": "/province"}
    assert comps[2]["value"] == {"path": "/address"}


def test_parse_a2ui_json_block_binds_fields():
    raw = """
[
  {
    "version": "v0.9",
    "updateComponents": {
      "surfaceId": "s1",
      "components": [
        {
          "id": "nameField",
          "component": "TextField",
          "value": ""
        }
      ]
    }
  },
  {
    "version": "v0.9",
    "updateDataModel": {
      "surfaceId": "s1",
      "value": {"name": ""}
    }
  }
]
"""
    msgs = parse_a2ui_json_block(raw, stage="test")
    comps = msgs[0]["updateComponents"]["components"]
    assert comps[0]["value"] == {"path": "/name"}
