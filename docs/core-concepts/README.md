# 核心概念

本部分用**短文**说明 Hubloom 里反复出现的词：是什么、在链路哪一环。  
实现细节、代码地图放到 [模块导读](../modules/README.md)；怎么配置、怎么写放到 [使用指南](../usage/README.md)。

---

## 先有一张主链路

**浏览器 / App → 企业后端（BFF）→ Hubloom Serve → Runtime → Agent ⇄ MCP → Markdown / SSE 回传**

- **Serve** — 产品 HTTP 门面
- **Runtime** — 装配并按会话启动一轮
- **Agent** — 编排决策：调工具、追问、确认或收工
- **MCP** — 把 OpenAPI 变成工具并调用企业 API
- **Skill** — 约束「该怎么办事」，不代替后端

细节与图见 [架构](architecture.md)。

---

## 本章路径

建议按这个顺序读：

1. [架构](architecture.md) — 整机怎么拼
2. [Runtime](runtime.md) — 办事内核怎么装配、怎么按会话跑
3. [Agent](agent.md) — 编排如何决策与循环
4. [MCP 协议](mcp-protocol.md) — 工具面从哪来
5. [Skill](skill.md) — 规程卡在哪（可与 [创建第一个 Skill](../guide/first-skill.md) 对照）

每篇保持概念级；要对照源码时再进模块导读。
