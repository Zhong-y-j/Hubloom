# 示例：列表行删除（可替换为任意资源）

> 仅作映射示意，**不是** A2UI 契约本身。换业务时改文案 / 字段 path / action 后缀即可，模板仍用 `list_row_actions` → `confirm_destructive`。

## 场景

用户要删除某类资源（示例：小区）。Agent 已 `call_tool` 拿到列表。

1. 最终回复：照抄模式 `list_row_actions`  
   - 标题改成资源名（如「小区列表」）  
   - 行字段 path 对齐工具返回（如 `name`、`address`）  
   - action：`request_delete_item`（或 `request_delete_<resource>`）  
   - 数据：`$hubloom_tool` → `body.items`（path 以工具为准）
2. 用户点击行内按钮后：再用 `confirm_destructive`  
   - `confirm_delete_item` 之后才 `call_tool` 删除

## 思考区（禁止 A2UI）

「已取列表，正式回复用 List；删除须先确认。」

## 最终回复形态

```text
请选择要删除的项（删除前会再确认）：

---a2ui_JSON---
<基于 references/templates/list_row_actions.json，替换文案与字段 path>
```
