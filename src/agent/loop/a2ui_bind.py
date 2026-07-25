"""把表单控件的字面量 value 改写成 data-model path 绑定。

LLM 常把 TextField 写成 ``"value": ""``，输入只停留在 DOM，不会写入 DataModel；
提交时 Button context 的 ``{path: "/name"}`` 解析为空，后端就收不到字段。
"""

from __future__ import annotations

import re
from typing import Any

_EDITABLE = frozenset({"TextField", "CheckBox", "Slider", "DateTimeInput", "ChoicePicker"})
_ID_SUFFIX = re.compile(
    r"(Field|Input|Picker|Check|Checkbox|Slider|Date|Time)?$",
    re.IGNORECASE,
)


def _is_path_ref(value: Any) -> bool:
    return isinstance(value, dict) and isinstance(value.get("path"), str)


def _path_from_checks(comp: dict[str, Any]) -> str | None:
    for check in comp.get("checks") or []:
        if not isinstance(check, dict):
            continue
        cond = check.get("condition")
        if not isinstance(cond, dict):
            continue
        args = cond.get("args")
        if not isinstance(args, dict):
            continue
        for raw in args.values():
            if _is_path_ref(raw):
                path = str(raw["path"]).strip()
                if path:
                    return path if path.startswith("/") else f"/{path}"
    return None


def _path_from_id(comp_id: str, model_keys: set[str]) -> str | None:
    cid = (comp_id or "").strip()
    if not cid:
        return None
    base = _ID_SUFFIX.sub("", cid) or cid
    candidates = [base, base[:1].lower() + base[1:] if base else base, cid]
    for key in candidates:
        if key in model_keys:
            return f"/{key}"
    if base and base[0].isalpha():
        return f"/{base[:1].lower() + base[1:]}"
    return None


def _collect_model_keys(messages: list[dict[str, Any]]) -> set[str]:
    keys: set[str] = set()
    for msg in messages:
        udm = msg.get("updateDataModel")
        if not isinstance(udm, dict):
            continue
        value = udm.get("value")
        if isinstance(value, dict):
            keys.update(str(k) for k in value.keys())
    return keys


def _ensure_model_key(
    messages: list[dict[str, Any]],
    *,
    surface_id: str | None,
    path: str,
    seed: Any,
) -> None:
    key = path.lstrip("/")
    if not key or "/" in key:
        return
    for msg in messages:
        udm = msg.get("updateDataModel")
        if not isinstance(udm, dict):
            continue
        if surface_id and udm.get("surfaceId") not in (None, surface_id):
            continue
        value = udm.get("value")
        if not isinstance(value, dict):
            continue
        if key not in value:
            value[key] = "" if seed is None else seed
        return
    # 没有 updateDataModel 时补一条（仅当有 surface）
    if not surface_id:
        return
    messages.append(
        {
            "version": "v0.9",
            "updateDataModel": {
                "surfaceId": surface_id,
                "value": {key: "" if seed is None else seed},
            },
        }
    )


def bind_editable_field_paths(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """就地修复：字面量 value → ``{path: "/…"}``，并确保 data model 有对应键。"""
    if not messages:
        return messages
    model_keys = _collect_model_keys(messages)
    for msg in messages:
        uc = msg.get("updateComponents")
        if not isinstance(uc, dict):
            continue
        surface_id = uc.get("surfaceId")
        comps = uc.get("components")
        if not isinstance(comps, list):
            continue
        for comp in comps:
            if not isinstance(comp, dict):
                continue
            if comp.get("component") not in _EDITABLE:
                continue
            value = comp.get("value")
            if _is_path_ref(value):
                continue
            path = _path_from_checks(comp) or _path_from_id(
                str(comp.get("id") or ""), model_keys
            )
            if not path:
                continue
            seed = value if value is not None else ""
            comp["value"] = {"path": path}
            _ensure_model_key(
                messages, surface_id=str(surface_id) if surface_id else None, path=path, seed=seed
            )
            model_keys.add(path.lstrip("/"))
    return messages
