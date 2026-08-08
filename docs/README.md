# Hubloom 文档

> 如果说 Spring Boot 是接口地基、Vue Admin 是后台脚手架，那 Hubloom 就是 AI Agent 时代的**基座脚手架**。

**快速把企业 API 编成私有化 Agent，策略约束下自动执行业务操作。**

---

跑通后，示例站大致如此——左边对话，右边交互：

![对话与交互面板](./assets/hubloom-chat-a2ui-panel.png)

例如：「在杭州西湖区加一个阳光花园小区，再给它加个钥匙柜」→ Agent 调真实 API → 缺参时弹出表单 → 确认后落库。业务逻辑仍在你的系统里；流程用 **Skill** 约束，也可经 **Events** 接口事件驱动触发。

---

## 定位

Hubloom 是可私有化的 **Agent 服务**，不是应用商店，也不替你重做业务系统。  
推荐 **浏览器 / App → 企业后端（BFF）→ Hubloom**：鉴权与限流放在你这边，Hubloom 负责编排与调工具；前端用示例站，或嵌进自有门户。

对外主要是这些 HTTP 接口（经 BFF 转发即可）：

| 能力 | 接口 |
| --- | --- |
| 对话办事 | `POST /v1/chat` · `POST /v1/chat/resume` · `GET /v1/chat/history` |
| 事件驱动 | `POST /v1/events`（需开启） |
| 企微入口 | `GET\|POST /v1/im/wecom/callback`（需开启） |

完整说明见 [API 参考](reference/api-reference.md)；产品定位见 [Hubloom 是什么](guide/what-is-hubloom.md)。

---

## 从这里开始

**先跑起来 →** [5 分钟快速上手](guide/quick-start.md)  
（想先搞清边界，可先看 [Hubloom 是什么](guide/what-is-hubloom.md)）

| 你是谁 | 去读 |
| --- | --- |
| 接业务 API | [接入 Swagger](usage/import-swagger.md) · [编写 Skill](usage/write-skill.md) |
| 嵌入门户 | [嵌入 Runtime](usage/embed-runtime.md) |
| 查配置 / 排错 | [配置项](reference/configuration.md) · [FAQ](reference/faq.md) |
| 翻源码二开 | [模块导读](modules/README.md) |

配好 `config/env.yaml`（LLM + Swagger）→ 启动 → 发一句能调到业务 API 的话。卡住了看 [安装与部署](guide/installation.md)。

---

## 文档地图

| 部分 | 说明 | 入口 |
| --- | --- | --- |
| 入门指南 | 是什么、安装、跑通、第一个 Skill | [guide/](guide/README.md) |
| 核心概念 | 架构与协议 | [core-concepts/](core-concepts/README.md) |
| 使用指南 | 配模型、接 Swagger、写 Skill、嵌入 | [usage/](usage/README.md) |
| 模块导读 | Runtime / Agent / MCP 等代码地图 | [modules/](modules/README.md) |
| 进阶功能 | 记忆、RAG、事件、企微（可选） | [advanced/](advanced/README.md) |
| 参考与社区 | API、配置、FAQ、贡献 | [reference/](reference/README.md) · [community/](community/README.md) |
