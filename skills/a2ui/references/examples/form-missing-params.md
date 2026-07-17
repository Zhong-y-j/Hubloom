# 示例：缺参表单（可替换为任意写操作）

> 仅作映射示意。模板用 `form_missing_params`；字段名以**当前缺参 / 工具 schema**为准。

## 场景

用户要创建/预约某业务，但缺少必填项（示例：车牌、日期）。

1. 思考区只记缺哪些字段，**不**贴 JSON  
2. 最终回复：一句说明 + `form_missing_params`  
   - `TextField` / `DateTimeInput` 只保留缺失项  
   - path 如 `/form/plateNo`（按领域改名）  
   - action：`submit_form` 或 `confirm_<action>`

## 最终回复形态

```text
好的，请补充以下信息后再继续：

---a2ui_JSON---
<基于 references/templates/form_missing_params.json，按缺参增删字段>
```
