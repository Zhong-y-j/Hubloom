# MCP

**MCP（Model Context Protocol）** 给大模型一条标准的「工具通道」：用统一方式发现和调用外部能力。

在 Hubloom 里，它主要做一件事：

> **把 OpenAPI / Swagger 变成 Agent 可调用的工具，从而在真实企业 API 上办事。**

可以这样理解分工：

- **Swagger** — 有哪些接口、参数长什么样
- **MCP** — 把契约变成可调用工具，并执行真实 HTTP
- **Skill** — 约束该怎么调、禁止什么；**不**代替 MCP 发请求
- **Agent** — 决定何时 `list_api` / `call_api`，并根据工具结果继续决策

模型面前常见是两个元工具：`list_api`（按分组发现）与 `call_api`（真正调用），避免把上百个接口一次性塞进上下文。业务 Token 由请求传入并透传到下游，不要写进配置文件。

换业务域时，优先换 `swagger_url`、下游地址与 Token，而不是重写 Runtime。对话、事件、企微可以换入口，后面往往仍走同一套 MCP 工具面。

可以把它想成：**Agent 管「要不要调、调哪个」；MCP 管「按契约把 HTTP 打出去」。**

协议规范全文不必先读；官网入口：[modelcontextprotocol.io](https://modelcontextprotocol.io/)。

怎么配自家 API 见 [接入 Swagger](../usage/import-swagger.md)；实现与代码地图见 [MCP Adapter 模块导读](../modules/mcp-adapter.md)。
