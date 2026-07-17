# Catalog 子集（第一期）

协议：**v0.9.1**  
Catalog：`https://a2ui.org/specification/v0_9/catalogs/basic/catalog.json`

## 允许的组件

| 组件 | 用途 |
|------|------|
| `Column` / `Row` | 布局 |
| `Text` | 标题与说明（`variant`: `h2` / `h3` / `body` / `caption`） |
| `TextField` | 短文本；`value` 用 `{ "path": "/..." }` |
| `DateTimeInput` | 日期/时间；`enableDate` / `enableTime` |
| `CheckBox` | 布尔 |
| `ChoicePicker` | 单选/多选；`value` 为字符串数组或 path |
| `Button` | 必须有 `child`（组件 id）和 `action` |
| `Card` | 单子节点容器 |
| `Divider` | 分隔 |
| `List` | 数据模板列表（工具结果填充） |

暂不使用：`Tabs`、`Modal`、`Image`、`Video`、`AudioPlayer`、`Slider`、`Icon`。

## 结构约束

- `Button.child` / `Card.child` → 组件 **id**，不是内联文案
- `List.children` → `{ "componentId": "<行模板 id>", "path": "/items" }`
- 行内字段用**相对 path**（如 `"text": { "path": "name" }`），不要写 `/items/0/name`
- `createSurface.catalogId` 使用上文 Catalog URL
- 同轮共用一个 `surfaceId`
- 不要在 JSON 里写颜色、字体、间距（外观由客户端 `--a2ui-*` 控制）
- 状态文案用 `Text` 绑字段；不要臆造 Badge / 内联样式
