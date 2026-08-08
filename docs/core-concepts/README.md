# 核心概念

本部分用短文说明 Hubloom 里反复出现的词，方便后面使用指南对照。

不要求按协议标准通读。先建立「请求怎么进来、工具怎么调、Skill 管什么」即可。

---

## 先有一张主链路

可以先按这条线理解（细节见架构章）：

**浏览器 / App → 企业后端（BFF）→ Hubloom Serve → 编排 → MCP 调企业 API → Markdown 回复**

- Serve 提供对话等 HTTP 接口
- 编排决定这一轮是调工具、追问还是收工
- MCP 把 OpenAPI/Swagger 变成可调用工具
- Skill 约束「该怎么办事」，不代替后端落库

---

## 本章路径

建议先读这三篇：

1. [架构](architecture.md) — Serve、Runtime、编排、工具怎么拼在一起
2. [MCP 协议](mcp-protocol.md) — HTTP API 如何变成 Agent 的工具
3. [Skill](skill.md) — Skill 在链路中的位置（可与 [创建第一个 Skill](../guide/first-skill.md) 对照）

读完这三篇，再进 [使用指南](../usage/README.md) 会顺很多。  
要对照源码、按目录深入实现 → [模块导读](../modules/README.md)。
