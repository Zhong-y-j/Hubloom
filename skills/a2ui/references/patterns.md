# UI 模式（业务无关）

按**交互意图**选模板，不要按行业名选。字段名、文案、action 后缀跟**当前工具 / 缺参**走。

| 模式 id | 何时用 | 模板文件 |
|---------|--------|----------|
| `form_missing_params` | 写操作缺必填参数 | `templates/form_missing_params.json` |
| `confirm_destructive` | 删除 / 取消 / 提交前确认 | `templates/confirm_destructive.json` |
| `list_row_actions` | 多条记录点选或行内操作 | `templates/list_row_actions.json` |

## 选型规则

1. **只读说明 / 查询汇总** → 仅 Markdown，不出 A2UI
2. **缺参** → `form_missing_params`；字段只含当前缺失项
3. **破坏性操作** → 先 `list_row_actions`（或已有上下文）→ 再 `confirm_destructive`；确认后才 `call_tool`
4. **长列表** → 必须 List + `$hubloom_tool` 哨兵，禁止手抄 items
5. **同一轮** → 最多一个主 surface

## Action 命名（中性前缀）

| 前缀 | 含义 |
|------|------|
| `submit_*` / `confirm_*` | 提交或确认（可随后调工具） |
| `request_delete_*` / `request_*` | 仅请求确认，**此时不调**破坏性工具 |
| `confirm_delete_*` | 用户已确认，可以 `call_tool` |
| `dismiss` / `cancel_*` | 取消 / 返回 |

`*` 换成当前资源类型（如 `item`、`order`），不要写死某一行业专名。

## 工具数据哨兵

```json
{
  "path": "/items",
  "value": { "$hubloom_tool": { "path": "body.items" } }
}
```

也可用 `"value": "$hubloom:body.items"`。  
可选 `"tool": "<工具名子串>"`；缺省用本轮最近一次成功工具结果。  
`body.items` 等 path 以**实际工具返回**为准，可替换。
