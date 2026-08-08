# Agent

**Agent** 是 Hubloom 的编排核心：根据用户话、历史、工具结果与 Skill，决定这一步做什么。

一句话：

> **在规程约束下，循环「决策 → 行动 / 追问 / 确认 → 观察」直到收工。**

Runtime 把能力装配好并启动一轮后，真正做选择的是 Agent。常见下一步可以粗记成四类：

- **act** — 调工具办事（经 MCP 打到企业 API）
- **ask** — 信息不够，先问人
- **await_confirm** — 高风险操作先等人确认
- **finish** — 收工，给出 Markdown 结论

Skill 约束「该怎么办事、禁止什么」；需要时 Agent 会 `read_skill` 读细则，但仍靠 MCP 真正调 API。Serve / 企微 / 事件只是换入口，进到内核后多半仍是同一套 Agent。

不同入口的「等人方式」不同（Wait Profile）：网页可挂起续跑，企微偏跨轮，事件入口通常不等人。概念见 [架构](architecture.md)。

可以把它想成：**Runtime 管「把一轮跑起来」，Agent 管「这一步怎么决策」，MCP 管「把 HTTP 打出去」。**

Agent **不管** HTTP 路由与鉴权（Serve / BFF），也不管 OpenAPI 如何变成工具、Skill 文件怎么写。

细讲（环内步骤、代码锚点）见 [Agent 模块导读](../modules/agent.md)。
