"""将工具返回填入 A2UI ``updateDataModel``（骨架由 LLM，数据由运行时）。

Agent 约定（二选一）：

1. 对象哨兵::

    "value": { "$hubloom_tool": { "path": "body.items" } }

   可选 ``tool``：匹配工具展示名 / 原始名子串（缺省用最近一次成功结果）。

2. 字符串哨兵::

    "value": "$hubloom:body.items"
"""

from __future__ import annotations

import json
import re
from typing import Any

from agents.agent_log import clip, cortex_log

_TOOL_BIND_KEY = "$hubloom_tool"
_TOOL_BIND_PREFIX = "$hubloom:"

_ABS_INTERP_RE = re.compile(r"\$\{(/[^}]+)\}")
_DYN_TEXT_KEYS = frozenset(
    {"text", "label", "description", "url", "title", "value"}
)


def parse_tool_result_json(result: str) -> Any | None:
    """解析工具返回文本为 JSON；失败返回 None。"""
    text = (result or "").strip()
    if not text:
        return None
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return None


def resolve_dotted_path(data: Any, path: str) -> Any:
    """按 ``body.items`` / ``body/items`` 取值。"""
    raw = (path or "").strip().strip("/")
    if not raw:
        return data
    parts = raw.replace("/", ".").split(".")
    cur: Any = data
    for part in parts:
        if not part:
            continue
        if isinstance(cur, dict):
            if part not in cur:
                return None
            cur = cur[part]
        elif isinstance(cur, list):
            try:
                cur = cur[int(part)]
            except (ValueError, IndexError):
                return None
        else:
            return None
    return cur


def is_tool_bind_value(value: Any) -> bool:
    if isinstance(value, str) and value.startswith(_TOOL_BIND_PREFIX):
        return True
    return isinstance(value, dict) and _TOOL_BIND_KEY in value


def _bind_spec(value: Any) -> tuple[str | None, str] | None:
    """返回 (tool_filter_or_none, dotted_path)。"""
    if isinstance(value, str) and value.startswith(_TOOL_BIND_PREFIX):
        return None, value[len(_TOOL_BIND_PREFIX) :].strip()
    if isinstance(value, dict) and _TOOL_BIND_KEY in value:
        spec = value[_TOOL_BIND_KEY]
        if not isinstance(spec, dict):
            return None, "body.items"
        tool = spec.get("tool")
        tool_f = str(tool).strip() if tool else None
        path = str(spec.get("path") or "body.items").strip()
        return tool_f or None, path or "body.items"
    return None


def pick_tool_payload(
    tool_results: list[tuple[str, str, bool]],
    *,
    tool_filter: str | None = None,
) -> Any | None:
    """从本轮工具结果中选一份 JSON 载荷（跳过 error）。"""
    for name, result, is_error in reversed(tool_results):
        if is_error:
            continue
        if tool_filter:
            needle = tool_filter.lower()
            if needle not in (name or "").lower():
                continue
        payload = parse_tool_result_json(result)
        if payload is not None:
            return payload
    return None


def resolve_tool_bind_value(
    value: Any,
    tool_results: list[tuple[str, str, bool]],
) -> Any:
    """若 value 是哨兵则解析为真实数据，否则原样返回。"""
    spec = _bind_spec(value)
    if spec is None:
        return value
    tool_filter, path = spec
    payload = pick_tool_payload(tool_results, tool_filter=tool_filter)
    if payload is None:
        cortex_log(
            "a2ui tool bind missed",
            tool_filter=tool_filter or "",
            path=path,
            available=[n for n, _, e in tool_results if not e],
        )
        return []
    resolved = resolve_dotted_path(payload, path)
    if resolved is None:
        cortex_log("a2ui tool bind path miss", path=path)
        return []
    cortex_log(
        "a2ui tool bind ok",
        path=path,
        tool_filter=tool_filter or "(last)",
        preview=clip(str(type(resolved).__name__), 40),
    )
    return resolved


def bind_tool_data_to_a2ui_messages(
    messages: list[dict[str, Any]],
    tool_results: list[tuple[str, str, bool]],
) -> list[dict[str, Any]]:
    """深拷贝 messages，替换工具哨兵，并修正常见 List/详情数据路径问题。"""
    if not messages:
        return messages

    out: list[dict[str, Any]] = []
    for msg in messages:
        if not isinstance(msg, dict):
            out.append(msg)
            continue
        if "updateDataModel" not in msg or not tool_results:
            out.append(dict(msg))
            continue
        udm = msg.get("updateDataModel")
        if not isinstance(udm, dict):
            out.append(dict(msg))
            continue
        value = udm.get("value")
        if not is_tool_bind_value(value):
            out.append(dict(msg))
            continue
        new_udm = dict(udm)
        new_udm["value"] = resolve_tool_bind_value(value, tool_results)
        new_msg = dict(msg)
        new_msg["updateDataModel"] = new_udm
        out.append(new_msg)

    return normalize_a2ui_messages(out)


def _list_template_paths(messages: list[dict[str, Any]]) -> list[tuple[str, str]]:
    """返回 [(componentId, dataPath), ...]。"""
    found: list[tuple[str, str]] = []
    for msg in messages:
        if not isinstance(msg, dict) or "updateComponents" not in msg:
            continue
        uc = msg.get("updateComponents")
        if not isinstance(uc, dict):
            continue
        comps = uc.get("components")
        if not isinstance(comps, list):
            continue
        for c in comps:
            if not isinstance(c, dict) or c.get("component") != "List":
                continue
            children = c.get("children")
            if not isinstance(children, dict):
                continue
            cid = str(children.get("componentId") or "").strip()
            path = str(children.get("path") or "").strip() or "/items"
            if cid:
                found.append((cid, path))
    return found


def _norm_data_path(path: str) -> str:
    p = (path or "").strip()
    if not p or p == "/":
        return "/"
    return p if p.startswith("/") else f"/{p}"


def _list_row_template_components(cid: str) -> list[dict[str, Any]]:
    """List 行兜底模板：名称 / 地址 / 启用状态（相对 path，绑定行内字段）。"""
    p = cid
    return [
        {"id": p, "component": "Card", "child": f"{p}__body"},
        {
            "id": f"{p}__body",
            "component": "Column",
            "children": [f"{p}__name", f"{p}__addr", f"{p}__status"],
        },
        {
            "id": f"{p}__name",
            "component": "Text",
            "text": {"path": "name"},
            "variant": "h3",
        },
        {
            "id": f"{p}__addr",
            "component": "Text",
            "text": {
                "call": "formatString",
                "args": {"value": "地址：${address}"},
                "returnType": "string",
            },
            "variant": "body",
        },
        {
            "id": f"{p}__status",
            "component": "Text",
            "text": {
                "call": "formatString",
                "args": {"value": "状态：${isActive}"},
                "returnType": "string",
            },
            "variant": "caption",
        },
    ]


def _thin_list_template_ids(
    comps: list[Any], cid: str
) -> set[str] | None:
    """若 ``cid`` 是「仅 name 的薄模板」，返回应移除的组件 id 集合；否则 None。"""
    by_id = {
        str(c.get("id")): c
        for c in comps
        if isinstance(c, dict) and c.get("id") is not None
    }
    root = by_id.get(cid)
    if root is None:
        return set()  # 缺失，调用方注入
    if root.get("component") != "Card":
        return None
    child_id = str(root.get("child") or "")
    child = by_id.get(child_id)
    if not isinstance(child, dict):
        return None
    if child.get("component") == "Text":
        text = child.get("text")
        only_name = isinstance(text, dict) and text.get("path") == "name"
        if only_name and (
            child_id.endswith("__label") or child_id == f"{cid}__label"
        ):
            return {cid, child_id}
        if only_name:
            return {cid, child_id}
    return None


def _harvest_abs_fields_from_value(value: Any, fields: set[str]) -> None:
    if isinstance(value, dict):
        path = value.get("path")
        if isinstance(path, str) and path.startswith("/"):
            top = path.strip("/").split("/")[0]
            if top:
                fields.add(top)
        if value.get("call") == "formatString":
            args = value.get("args")
            raw = ""
            if isinstance(args, dict):
                raw = str(args.get("value") or "")
            for m in _ABS_INTERP_RE.finditer(raw):
                top = m.group(1).strip("/").split("/")[0]
                if top:
                    fields.add(top)
        for v in value.values():
            _harvest_abs_fields_from_value(v, fields)
    elif isinstance(value, list):
        for item in value:
            _harvest_abs_fields_from_value(item, fields)


def _collect_root_abs_fields(messages: list[dict[str, Any]]) -> set[str]:
    """组件里出现的绝对 path 顶层字段名（如 /paidTime → paidTime）。"""
    fields: set[str] = set()
    for msg in messages:
        uc = msg.get("updateComponents") if isinstance(msg, dict) else None
        if not isinstance(uc, dict):
            continue
        comps = uc.get("components")
        if not isinstance(comps, list):
            continue
        for c in comps:
            if isinstance(c, dict):
                _harvest_abs_fields_from_value(c, fields)
    return fields


def _unwrap_singleton_detail_records(
    messages: list[dict[str, Any]],
    list_refs: list[tuple[str, str]],
) -> None:
    """把误放在 List path 下的「单条详情对象」摊到 ``/``。

    典型错误：path=/orderItems, value=[{整单含 orderItems/orderRemarks/...}]，
    而 Text 绑定的是 /status、/paidTime。
    """
    del list_refs  # 保留签名对称；判定主要靠嵌套同名键 / 根字段重合
    root_fields = _collect_root_abs_fields(messages)
    for msg in messages:
        udm = msg.get("updateDataModel") if isinstance(msg, dict) else None
        if not isinstance(udm, dict):
            continue
        value = udm.get("value")
        path = _norm_data_path(str(udm.get("path") or "/"))
        if path == "/":
            continue
        if not (
            isinstance(value, list)
            and len(value) == 1
            and isinstance(value[0], dict)
        ):
            continue
        obj = value[0]
        path_key = path.strip("/")
        nested_same = bool(path_key) and isinstance(obj.get(path_key), list)
        overlap = len(root_fields.intersection(obj.keys()))
        if not nested_same and overlap < 2:
            continue
        udm["path"] = "/"
        udm["value"] = obj
        cortex_log(
            "a2ui normalize unwrap detail",
            from_path=path,
            overlap=overlap,
            nested_same=nested_same,
            keys=clip(",".join(list(obj.keys())[:8]), 120),
        )


def _component_subtree_ids(comps: list[Any], root_id: str) -> set[str]:
    by_id = {
        str(c.get("id")): c
        for c in comps
        if isinstance(c, dict) and c.get("id") is not None
    }
    seen: set[str] = set()
    stack = [root_id]
    while stack:
        cid = stack.pop()
        if not cid or cid in seen:
            continue
        seen.add(cid)
        c = by_id.get(cid)
        if not isinstance(c, dict):
            continue
        child = c.get("child")
        if child is not None:
            stack.append(str(child))
        children = c.get("children")
        if isinstance(children, list):
            stack.extend(str(x) for x in children)
        elif isinstance(children, dict):
            tid = children.get("componentId")
            if tid:
                stack.append(str(tid))
        for key in ("trigger", "content"):
            if c.get(key) is not None:
                stack.append(str(c[key]))
        tabs = c.get("tabs")
        if isinstance(tabs, list):
            for tab in tabs:
                if isinstance(tab, dict) and tab.get("child") is not None:
                    stack.append(str(tab["child"]))
    return seen


def _relativize_dyn_value(value: Any) -> Any:
    """List 行内：绝对 path / formatString ${/x} → 相对。"""
    if isinstance(value, dict):
        out = dict(value)
        path = out.get("path")
        if isinstance(path, str) and path.startswith("/"):
            out["path"] = path.lstrip("/")
        if out.get("call") == "formatString":
            args = out.get("args")
            if isinstance(args, dict):
                args = dict(args)
                raw = args.get("value")
                if isinstance(raw, str):
                    args["value"] = _ABS_INTERP_RE.sub(
                        lambda m: "${" + m.group(1).lstrip("/") + "}",
                        raw,
                    )
                out["args"] = args
            if "returnType" not in out:
                out["returnType"] = "string"
        for k, v in list(out.items()):
            if k in ("path", "args", "call", "returnType"):
                continue
            out[k] = _relativize_dyn_value(v)
        return out
    if isinstance(value, list):
        return [_relativize_dyn_value(v) for v in value]
    return value


def _relativize_list_row_bindings(
    messages: list[dict[str, Any]],
    list_refs: list[tuple[str, str]],
) -> None:
    for msg in messages:
        uc = msg.get("updateComponents") if isinstance(msg, dict) else None
        if not isinstance(uc, dict):
            continue
        comps = uc.get("components")
        if not isinstance(comps, list):
            continue
        row_ids: set[str] = set()
        for cid, _path in list_refs:
            row_ids |= _component_subtree_ids(comps, cid)
        if not row_ids:
            continue
        changed = 0
        for c in comps:
            if not isinstance(c, dict):
                continue
            if str(c.get("id")) not in row_ids:
                continue
            for key in _DYN_TEXT_KEYS:
                if key not in c:
                    continue
                before = c[key]
                after = _relativize_dyn_value(before)
                if after != before:
                    c[key] = after
                    changed += 1
        if changed:
            cortex_log("a2ui normalize relativize list paths", n=changed)


def normalize_a2ui_messages(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """修正 LLM 常见 A2UI 结构错误。

    - 详情对象误塞进 List path（单元素数组）→ 摊到 ``/``
    - List ``path: /items`` 但数组写在 ``/`` → 改为 ``/items``
    - List 缺行模板 / 仅 name → 补名称/地址/状态
    - 行模板里误用绝对 path（``/unitPrice``、``${/quantity}``）→ 相对 path
    """
    if not messages:
        return messages

    out: list[dict[str, Any]] = []
    for msg in messages:
        if not isinstance(msg, dict):
            out.append(msg)
            continue
        cloned = dict(msg)
        if "updateComponents" in cloned and isinstance(cloned["updateComponents"], dict):
            uc = dict(cloned["updateComponents"])
            comps = uc.get("components")
            if isinstance(comps, list):
                uc["components"] = [
                    dict(c) if isinstance(c, dict) else c for c in comps
                ]
            cloned["updateComponents"] = uc
        if "updateDataModel" in cloned and isinstance(cloned["updateDataModel"], dict):
            cloned["updateDataModel"] = dict(cloned["updateDataModel"])
        out.append(cloned)

    list_refs = _list_template_paths(out)

    # 1) 详情单对象误放在列表 path 下
    _unwrap_singleton_detail_records(out, list_refs)

    if not list_refs:
        return out

    # 2) 对齐 updateDataModel：根路径上的裸数组 → List 声明的 path
    preferred = _norm_data_path(list_refs[0][1])
    for msg in out:
        udm = msg.get("updateDataModel")
        if not isinstance(udm, dict):
            continue
        value = udm.get("value")
        path = _norm_data_path(str(udm.get("path") or "/"))
        if isinstance(value, list) and path == "/" and preferred != "/":
            udm["path"] = preferred
            cortex_log(
                "a2ui normalize data path",
                from_path="/",
                to_path=preferred,
                n=len(value),
            )
        elif isinstance(value, list) and path == "/" and preferred == "/":
            key = list_refs[0][1].strip("/") or "items"
            if key and key != "/":
                udm["value"] = {key: value}
                cortex_log("a2ui normalize wrap items", key=key, n=len(value))

    # 3) 补全 / 加厚 List 行模板
    for msg in out:
        uc = msg.get("updateComponents")
        if not isinstance(uc, dict):
            continue
        comps = uc.get("components")
        if not isinstance(comps, list):
            continue

        remove_ids: set[str] = set()
        inject_cids: list[str] = []
        for cid, _path in list_refs:
            thin = _thin_list_template_ids(comps, cid)
            if thin is None:
                continue
            if thin:
                remove_ids |= thin
            inject_cids.append(cid)

        if not inject_cids:
            continue

        kept = [
            c
            for c in comps
            if not (isinstance(c, dict) and str(c.get("id")) in remove_ids)
        ]
        extras: list[dict[str, Any]] = []
        seen: set[str] = {
            str(c.get("id"))
            for c in kept
            if isinstance(c, dict) and c.get("id") is not None
        }
        for cid in inject_cids:
            if cid in seen:
                continue
            for piece in _list_row_template_components(cid):
                pid = str(piece["id"])
                if pid in seen:
                    continue
                extras.append(piece)
                seen.add(pid)
            cortex_log("a2ui normalize inject list template", component_id=cid)

        uc["components"] = kept + extras

    # 4) 行内绝对 path → 相对
    _relativize_list_row_bindings(out, list_refs)

    # 5) 列表字段若是图片 URL：Text → Image（或旁路加 Image）
    _upgrade_list_text_to_images(out, list_refs)

    return out


_IMAGE_EXT = (".jpg", ".jpeg", ".png", ".gif", ".webp", ".bmp", ".svg")


def _looks_like_image_url(value: Any) -> bool:
    if not isinstance(value, str):
        return False
    s = value.strip().lower()
    if not (s.startswith("http://") or s.startswith("https://")):
        return False
    path = s.split("?", 1)[0]
    return any(path.endswith(ext) for ext in _IMAGE_EXT)


def _list_items_for_path(
    messages: list[dict[str, Any]], list_path: str
) -> list[Any]:
    want = _norm_data_path(list_path)
    for msg in messages:
        udm = msg.get("updateDataModel") if isinstance(msg, dict) else None
        if not isinstance(udm, dict):
            continue
        value = udm.get("value")
        path = _norm_data_path(str(udm.get("path") or "/"))
        if path == want and isinstance(value, list):
            return value
        if path == "/" and isinstance(value, dict):
            key = want.strip("/")
            nested = value.get(key)
            if isinstance(nested, list):
                return nested
    return []


def _upgrade_list_text_to_images(
    messages: list[dict[str, Any]],
    list_refs: list[tuple[str, str]],
) -> None:
    """行内 Text 绑到图片 URL 字段时改为 Image（混排则 Text+Image，坏图由前端隐藏）。"""
    for msg in messages:
        uc = msg.get("updateComponents") if isinstance(msg, dict) else None
        if not isinstance(uc, dict):
            continue
        comps = uc.get("components")
        if not isinstance(comps, list):
            continue

        by_id = {
            str(c.get("id")): c
            for c in comps
            if isinstance(c, dict) and c.get("id") is not None
        }

        for cid, list_path in list_refs:
            items = _list_items_for_path(messages, list_path)
            if not items:
                continue
            row_ids = _component_subtree_ids(comps, cid)
            for rid in list(row_ids):
                c = by_id.get(rid)
                if not isinstance(c, dict) or c.get("component") != "Text":
                    continue
                text = c.get("text")
                if not isinstance(text, dict):
                    continue
                field = str(text.get("path") or "").strip().lstrip("/")
                if not field or "/" in field:
                    continue
                vals = [
                    it.get(field)
                    for it in items
                    if isinstance(it, dict) and field in it
                ]
                if not vals:
                    continue
                img_n = sum(1 for v in vals if _looks_like_image_url(v))
                if img_n == 0:
                    continue
                all_img = img_n == len(vals)
                img_id = f"{rid}__img"
                if img_id in by_id:
                    continue
                image_comp = {
                    "id": img_id,
                    "component": "Image",
                    "url": {"path": field},
                    "description": field,
                    "fit": "contain",
                    "variant": "mediumFeature",
                }
                if all_img:
                    c.clear()
                    c.update(
                        {
                            "id": rid,
                            "component": "Image",
                            "url": {"path": field},
                            "description": field,
                            "fit": "contain",
                            "variant": "mediumFeature",
                        }
                    )
                    by_id[rid] = c
                    cortex_log(
                        "a2ui normalize text→image",
                        component_id=rid,
                        field=field,
                        n=img_n,
                    )
                else:
                    # 混排：在父 Column 中追加 Image；找不到父则把 Text 包进 Column
                    parent = None
                    for p in comps:
                        if not isinstance(p, dict):
                            continue
                        children = p.get("children")
                        if isinstance(children, list) and rid in [
                            str(x) for x in children
                        ]:
                            parent = p
                            break
                    if parent is not None and isinstance(parent.get("children"), list):
                        kids = [str(x) for x in parent["children"]]
                        if img_id not in kids:
                            parent["children"] = kids + [img_id]
                        comps.append(image_comp)
                        by_id[img_id] = image_comp
                    else:
                        wrap_id = f"{rid}__wrap"
                        if wrap_id in by_id:
                            continue
                        text_copy = dict(c)
                        text_copy["id"] = f"{rid}__txt"
                        c.clear()
                        c.update(
                            {
                                "id": rid,
                                "component": "Column",
                                "children": [f"{rid}__txt", img_id],
                            }
                        )
                        comps.append(text_copy)
                        comps.append(image_comp)
                        by_id[f"{rid}__txt"] = text_copy
                        by_id[img_id] = image_comp
                    cortex_log(
                        "a2ui normalize add image beside text",
                        component_id=rid,
                        field=field,
                        img_n=img_n,
                        total=len(vals),
                    )
