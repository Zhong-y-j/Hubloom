#!/usr/bin/env python3
"""校验 A2UI 模板 / 模型产出是否为合法消息数组（轻量、无第三方依赖）。

用法::

    python skills/a2ui/scripts/validate_a2ui.py skills/a2ui/references/templates/*.json
    python skills/a2ui/scripts/validate_a2ui.py path/to/model_output.json
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ALLOWED_OPS = frozenset(
    {"createSurface", "updateComponents", "updateDataModel", "deleteSurface"}
)
ALLOWED_COMPONENTS = frozenset(
    {
        "Column",
        "Row",
        "Text",
        "TextField",
        "DateTimeInput",
        "CheckBox",
        "ChoicePicker",
        "Button",
        "Card",
        "Divider",
        "List",
    }
)
CATALOG_ID = "https://a2ui.org/specification/v0_9/catalogs/basic/catalog.json"


def _validate_message(msg: object, index: int) -> list[str]:
    errors: list[str] = []
    if not isinstance(msg, dict):
        return [f"[{index}] message must be object"]
    if msg.get("version") != "v0.9.1":
        errors.append(f"[{index}] version must be v0.9.1")
    ops = [k for k in ALLOWED_OPS if k in msg]
    if len(ops) != 1:
        errors.append(f"[{index}] must contain exactly one of {sorted(ALLOWED_OPS)}")
        return errors
    op = ops[0]
    body = msg[op]
    if not isinstance(body, dict):
        errors.append(f"[{index}].{op} must be object")
        return errors
    if op == "createSurface":
        if body.get("catalogId") != CATALOG_ID:
            errors.append(f"[{index}] catalogId mismatch")
        if not body.get("surfaceId"):
            errors.append(f"[{index}] createSurface.surfaceId required")
    if op == "updateComponents":
        comps = body.get("components")
        if not isinstance(comps, list):
            errors.append(f"[{index}] updateComponents.components must be array")
        else:
            for c in comps:
                if not isinstance(c, dict):
                    errors.append(f"[{index}] component entry must be object")
                    continue
                name = c.get("component")
                if name not in ALLOWED_COMPONENTS:
                    errors.append(f"[{index}] unknown component: {name!r}")
                if not c.get("id"):
                    errors.append(f"[{index}] component missing id")
                if name == "Button" and ("child" not in c or "action" not in c):
                    errors.append(f"[{index}] Button {c.get('id')!r} needs child+action")
    return errors


def validate_document(data: object) -> list[str]:
    if not isinstance(data, list):
        return ["root must be a JSON array of A2UI messages"]
    if not data:
        return ["array must not be empty"]
    errors: list[str] = []
    for i, msg in enumerate(data):
        errors.extend(_validate_message(msg, i))
    return errors


def main(argv: list[str]) -> int:
    if len(argv) < 2:
        print(__doc__.strip(), file=sys.stderr)
        return 2
    failed = 0
    for arg in argv[1:]:
        path = Path(arg)
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            print(f"FAIL {path}: {exc}")
            failed += 1
            continue
        errors = validate_document(data)
        if errors:
            print(f"FAIL {path}")
            for err in errors:
                print(f"  - {err}")
            failed += 1
        else:
            print(f"OK   {path}")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
