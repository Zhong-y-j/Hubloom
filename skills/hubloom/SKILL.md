---
name: hubloom
description: >-
  Hubloom 对话 Agent 平台用法：经元工具 list_tools/call_tool 调用后端 OpenAPI，
  按 prompt 中的 API 分组选 tag。不用于编写业务细则或替代 Swagger 文档。
priority: normal
---

# Hubloom

面向 **Hubloom 对话 Agent** 的公共平台 Skill（说明文档）。  
**当前未接入 Agent 运行时**；分组目录仍由 system prompt 中的 API catalog 注入。

## 何时使用

- 理解 Hubloom 如何把用户意图落到 HTTP API
- 说明 Agent 可见工具、调用顺序与鉴权约定
- 排障：为何看不到全量 OpenAPI 工具、如何选 tag

## 何时不要用

- 不要当作某个业务域（优惠券、洗车单等）的操作手册
- 不要替代 OpenAPI / Swagger 的字段级文档
- 不要假设存在「按业务自动生成的多个 Skill」——本仓库以本文件为平台说明

## 运行时模型（简明）

```
用户话术
  → HubloomAgent / Cortex Thought
  → 仅注册元工具：list_tools、call_tool
  → 单个全量 MCP worker（OpenAPI → 工具）
  → 业务 HTTP API
```

- Agent **不会**把成百上千个业务工具直接挂进工具列表
- System prompt 中有 **【API 分组（OpenAPI tag）】** 摘要（来自 Swagger），用于选 tag
- 具体参数 schema 以 `list_tools` 返回为准

## 操作流程（Agent 侧）

1. 根据用户意图，对照 prompt 里的 API 分组，选定 **一个** OpenAPI `tag`
2. `list_tools(tag="<tag>")` — 查看该组工具名与 parameters
3. `call_tool(tag="<tag>", tool_name="<name>", arguments={...})` — 执行
4. 用自然语言汇总结果；失败时如实说明，不编造数据

## 工具绑定

| 工具 | 作用 |
|------|------|
| `list_tools` | 按 tag 发现工具（只读 schema） |
| `call_tool` | 按 tag + tool_name 调用业务接口 |

约束：

- 创建 / 查询 / 更新 / 删除等业务操作都必须走 `call_tool`
- `list_tools` 不能代替实际调用
- 用户 Token 经会话注入，由 MCP 转发到下游 HTTP（勿在话术里粘贴密钥）

## 示例话术

- 「帮我查一下现在有哪些用户」→ 选 User（或同类）tag → list_tools → call_tool
- 「创建一个首页 Banner」→ Banner tag → list_tools → call_tool 创建类接口

## 输出要求

- 中文、简洁；关键 ID / 状态写清楚
- 基于工具真实返回，不臆造列表或成功状态
- 缺参数时先追问，再调用写操作
