---
name: a2ui
description: >-
  何时用 Markdown、何时用 A2UI Generative UI；输出分隔约定与最小组件子集。
  用于缺参表单、确认卡等交互面，不替代 OpenAPI / 业务细则，也不用于长文档排版。
priority: normal
---

# A2UI（Agent → UI）

面向 **Hubloom 对话 Agent** 的 Generative UI Skill。  
对齐 [A2UI Agent Development](https://a2ui.org/guides/agent-development/) 的 Prompt 思路：  
**role + 业务 UI 规则 + 裁剪 Catalog + few-shot**；运行时会切分最终回复中的 A2UI 并下发给前端。

协议版本：**v0.9.1**  
Catalog：`https://a2ui.org/specification/v0_9/catalogs/basic/catalog.json`（Basic Catalog）

---

## 输出位置（最重要 — 先读）

Hubloom 有「思考过程」与「最终回复」两块。**A2UI 只能出现在最终回复。**

| 阶段 | 能否出现 `---a2ui_JSON---` / A2UI JSON |
|------|----------------------------------------|
| 研判 / 重规划 / 执行后总结（内部笔记） | **禁止** |
| 工具执行（call_tool / list_tools、进度备忘） | **禁止** |
| **最终正式回复**（面向用户的那一段） | **允许**（需要交互 UI 时） |

错误示范（禁止）：在思考笔记里写「我准备出表单」后直接贴 `---a2ui_JSON---` 与 JSON。  
正确做法：思考区只用一两句说明「缺 name/address，正式回复用表单收集」；**把分隔符与 JSON 全部留给最终回复**。

若最终回复只需要纯文字说明，**不要**输出分隔符。缺参时应优先用最终回复里的 A2UI 表单，而不是在最终回复里用长列表追问、却把 JSON 写进思考区。

---

## 何时使用

在**最终回复**中需要用户 **填表、确认、点选** 时，追加 A2UI 消息，例如：

- 调用写操作前缺必填参数 → 表单（TextField / DateTimeInput / ChoicePicker 等）
- 破坏性操作前 → 确认卡（Card + Button）
- 需要结构化选项而不是纯文字追问 → ChoicePicker / 简短表单

## 何时不要用

- **长文档、规则说明、表格叙述** → 只用 **Markdown**（不要拆成一堆 Card/List）
- 纯查询结果的文字汇总 → Markdown
- **思考过程 / 内部笔记 / 执行进度** → 禁止 A2UI（见上文「输出位置」）
- 不要输出 CSS / HTML / 任意脚本；样式由客户端 `--a2ui-*` 控制
- 不要使用未列出的 Catalog 组件（见下方「允许的组件」）

---

## 输出格式（必须遵守）

**仅**在最终对用户可见的回复中，可按下面格式连接两部分：

```text
<自然语言 Markdown，可为空但推荐有一句说明>

---a2ui_JSON---
<单个 JSON 数组：若干 A2UI 消息对象>
```

规则：

1. 分隔符必须是单独一行：`---a2ui_JSON---`（恰好三横，不要四横或包进代码块）
2. 分隔符之后 **只能是** JSON 数组，不要用 Markdown 代码围栏包住
3. **不需要**交互 UI 时：**不要**输出分隔符和 JSON
4. **禁止**在思考过程、工具调用说明、执行备忘中输出分隔符或任何 A2UI JSON
5. JSON 数组元素顺序建议：
   1. `createSurface`
   2. `updateComponents`
   3. `updateDataModel`（如有绑定数据）

每条消息必须带 `"version": "v0.9.1"`，且 **恰好包含** 下列键之一：  
`createSurface` | `updateComponents` | `updateDataModel` | `deleteSurface`

---

## 允许的组件（第一期子集）

只使用 Basic Catalog 中的：

| 组件 | 用途 |
|------|------|
| `Column` / `Row` | 布局 |
| `Text` | 标题与说明（`variant`: `h2`/`h3`/`body`/`caption`） |
| `TextField` | 短文本输入；`value` 用 `{ "path": "/..." }` |
| `DateTimeInput` | 日期/时间；`enableDate` / `enableTime` |
| `CheckBox` | 布尔 |
| `ChoicePicker` | 单选/多选；`value` 为 **字符串数组** 或 path |
| `Button` | 必须有 `child`（通常是 Text 的 id）和 `action` |
| `Card` | 单子节点容器 |
| `Divider` | 分隔 |

暂不使用：`List` 模板、`Tabs`、`Modal`、`Image`、`Video`、`AudioPlayer`、`Slider`、`Icon`（除非产品明确放开）。

### 关键约束

- `Button`：**必须**提供 `action`（如 `{ "event": { "name": "confirm_booking" } }`）
- `Button.child` / `Card.child`：指向 **组件 id**，不是内联文案
- 动态文案与输入：优先 ` { "path": "/foo/bar" } `，在 `updateDataModel` 里给初值
- `surfaceId` 本轮内一致；`createSurface.catalogId` 使用上文 Catalog URL
- **不要**在 JSON 里写颜色、字体、间距（外观由客户端主题决定）

---

## 业务 UI 规则（ui_description）

1. **缺参填表**：在**最终回复**里先一句话说明缺什么，再出表单；字段只包含当前缺失项，不要堆全部业务字段。思考区只记「缺哪些字段」，不要贴 JSON。
2. **确认操作**：标题问句 + 摘要 Text（可 path 绑定）+「确认」主按钮 +「取消/返回」次按钮（均在最终回复的 A2UI 中）。
3. **查询/说明**：仅 Markdown；不要为了「好看」强行出 Card 列表。
4. **工具调用之后**：用工具真实返回填 `updateDataModel` 或 Text；禁止编造订单号、状态。
5. **同一轮**：最多一个主 surface；不要并行多个无关表单。
6. **缺参时**：优先最终回复出 A2UI 表单；避免最终回复只写长列表追问、却把表单 JSON 写进思考过程。

---

## Few-shot：预约缺参表单

用户意图：预约洗车但缺车牌等。

思考过程（内部笔记，**不要**含分隔符或 JSON）示例：  
「缺车牌与时间，正式回复用表单收集；暂不 call_tool。」

最终回复：

```text
好的，请补充以下信息后再确认预约：

---a2ui_JSON---
[  {
    "version": "v0.9.1",
    "createSurface": {
      "surfaceId": "booking",
      "catalogId": "https://a2ui.org/specification/v0_9/catalogs/basic/catalog.json"
    }
  },
  {
    "version": "v0.9.1",
    "updateComponents": {
      "surfaceId": "booking",
      "components": [
        {
          "id": "root",
          "component": "Column",
          "children": ["title", "plate", "date", "actions"]
        },
        {
          "id": "title",
          "component": "Text",
          "text": "创建洗车预约",
          "variant": "h3"
        },
        {
          "id": "plate",
          "component": "TextField",
          "label": "车牌号",
          "value": { "path": "/booking/plateNo" }
        },
        {
          "id": "date",
          "component": "DateTimeInput",
          "label": "预约日期",
          "value": { "path": "/booking/date" },
          "enableDate": true,
          "enableTime": false
        },
        {
          "id": "actions",
          "component": "Row",
          "children": ["submit-btn", "cancel-btn"]
        },
        { "id": "submit-label", "component": "Text", "text": "确认预约" },
        {
          "id": "submit-btn",
          "component": "Button",
          "child": "submit-label",
          "variant": "primary",
          "action": { "event": { "name": "confirm_booking" } }
        },
        { "id": "cancel-label", "component": "Text", "text": "取消" },
        {
          "id": "cancel-btn",
          "component": "Button",
          "child": "cancel-label",
          "action": { "event": { "name": "cancel_booking" } }
        }
      ]
    }
  },
  {
    "version": "v0.9.1",
    "updateDataModel": {
      "surfaceId": "booking",
      "path": "/booking",
      "value": {
        "plateNo": "",
        "date": "2026-07-20T10:00:00"
      }
    }
  }
]
```

---

## Few-shot：确认取消

```text
即将取消该订单，请确认：

---a2ui_JSON---
[
  {
    "version": "v0.9.1",
    "createSurface": {
      "surfaceId": "confirm",
      "catalogId": "https://a2ui.org/specification/v0_9/catalogs/basic/catalog.json"
    }
  },
  {
    "version": "v0.9.1",
    "updateComponents": {
      "surfaceId": "confirm",
      "components": [
        { "id": "root", "component": "Card", "child": "body" },
        {
          "id": "body",
          "component": "Column",
          "children": ["title", "summary", "actions"]
        },
        {
          "id": "title",
          "component": "Text",
          "text": "确认取消订单？",
          "variant": "h3"
        },
        {
          "id": "summary",
          "component": "Text",
          "text": { "path": "/order/summary" },
          "variant": "body"
        },
        {
          "id": "actions",
          "component": "Row",
          "children": ["yes-btn", "no-btn"]
        },
        { "id": "yes-label", "component": "Text", "text": "确认取消" },
        {
          "id": "yes-btn",
          "component": "Button",
          "child": "yes-label",
          "variant": "primary",
          "action": {
            "event": {
              "name": "cancel_order",
              "context": { "orderId": { "path": "/order/id" } }
            }
          }
        },
        { "id": "no-label", "component": "Text", "text": "返回" },
        {
          "id": "no-btn",
          "component": "Button",
          "child": "no-label",
          "action": { "event": { "name": "dismiss" } }
        }
      ]
    }
  },
  {
    "version": "v0.9.1",
    "updateDataModel": {
      "surfaceId": "confirm",
      "path": "/order",
      "value": {
        "id": "ORD-001",
        "summary": "订单 ORD-001 · 示例小区 · 粤B12345 · 明天 10:00"
      }
    }
  }
]
```

---

## 与平台其它能力的关系

- **OpenAPI / 元工具**（`list_tools` / `call_tool`）：仍按 `hubloom` Skill 执行业务；A2UI 只负责 **交互面**，不替代真实 API 调用。
- **校验工具**（规划中）：如 `validate_a2ui`，在发出给客户端前自检 JSON；本文件不定义工具实现。
- **客户端**：Button 的 `action.event` 由宿主回传。当前 demo：拼成用户消息 `[A2UI:<name>]` + 字段行，再走 `/v1/chat`。
- Agent 收到以 `[A2UI:` 开头的用户消息时：视为表单/确认结果，按字段直接调用业务工具，不要再追问已提供的字段。

---

## 自检清单（输出前）

- [ ] `---a2ui_JSON---` **只**出现在最终正式回复，思考/执行阶段完全没有
- [ ] 无交互需求时，未出现 `---a2ui_JSON---`
- [ ] JSON 为数组，且含 `createSurface` + `updateComponents`
- [ ] 仅使用「允许的组件」
- [ ] 每个 `Button` 有 `child` + `action`
- [ ] path 绑定的字段在 `updateDataModel` 中有初值
- [ ] 说明性长文未强行拆成 A2UI
- [ ] 分隔符为恰好一行 `---a2ui_JSON---`，JSON 无代码围栏
