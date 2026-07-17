# references/

本目录是 A2UI Skill 的**可维护真相来源**（业务无关）。

| 路径 | 是否注入运行时 prompt | 说明 |
|------|----------------------|------|
| `catalog-subset.md` | 是 | 允许组件与结构约束 |
| `patterns.md` | 是 | 模式选型与 action 约定 |
| `templates/*.json` | 是 | 可照抄的消息数组骨架 |
| `examples/*.md` | **否** | 领域映射示例，换业务可改/删 |

运行时由 `skills.loader` 自动把上表「是」的文件追加到 `a2ui` Skill 正文后。  
`examples/` 给人与 Cursor 维护用，避免把某一行业写进通用 prompt。
