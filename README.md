# Hubloom

> 如果说 Spring Boot 是接口地基、Vue Admin 是后台脚手架，那 Hubloom 就是 AI Agent 时代的**基座脚手架**。

**快速把企业 API 编成私有化 Agent，策略约束下自动执行业务操作。**

接上现有的 Swagger/OpenAPI，用自然语言在真实业务 API 上办事。业务逻辑仍在你的系统里；Hubloom 是可私有化的 **Agent 服务**，推荐经 **企业后端（BFF）** 转发接入（鉴权 / 限流放在你这边）。流程用 **Skill** 约束，也可经 **Events** 事件驱动触发。

完整手册见 [在线文档](https://zhong-y-j.github.io/Hubloom/)。

---

## 界面预览

对话办事：自然语言驱动工具调用，Markdown 呈现结论（过程可展开复盘）。

![对话与交互面板](./docs/assets/hubloom-chat-a2ui-panel.png)

创建完成后用表格核对系统状态。

![结果核对](./docs/assets/hubloom-chat-result-tables.png)

---

## 特性

- **契约即能力**：OpenAPI/Swagger 映射为工具面，换业务域主要换配置
- **策略约束办事**：Skill（含可选 Playbook）约束 Agent 怎么查、怎么确认、什么不能做
- **对话即闭环**：决策 → 调 API / 追问 / 确认 → 收工；结论用 Markdown
- **多入口同一 Runtime**：Web 对话、`POST /v1/events`、企微回调（后两者按需开启）
- **可私有化嵌入**：Hubloom Serve 提供产品 API；也可把 Runtime 嵌进自有门户
- **主路径优先**：记忆增强、RAG、A2A 等可选，默认不挡「先跑通」

---

## 快速开始

### 环境要求

- Python 3.12+
- [uv](https://github.com/astral-sh/uv)（推荐）或 pip
- **Redis**（必填）
- Node.js（仅跑演示前端时需要）

### 1. 安装与配置

```bash
uv sync
cp config/env.example.yaml config/env.yaml
```

在 `config/env.yaml` 中至少填写 `llm.*`、`redis.url`；启用 MCP 时再配 `mcp.swagger_url` / `base_url`。  
业务 Bearer 由请求传入，不要写进配置文件。

### 2. 启动

```bash
# 产品 API（默认 :8765）
PYTHONPATH=src uv run python main.py

# 演示前端（另开终端）
cd examples/chat/web && npm install && npm run dev
```

- 对话页：http://127.0.0.1:5173/
- API 文档：http://127.0.0.1:8765/docs

```bash
curl -s http://127.0.0.1:8765/v1/chat \
  -H "Content-Type: application/json" \
  -H "X-Session-Id: demo-session" \
  -H "X-MCP-Token: your-business-token" \
  -d '{"message":"你好，你能做什么？","stream":false,"wait_profile":"interactive"}'
```

更细的安装、事件与企微接入见 [快速上手](https://zhong-y-j.github.io/Hubloom/#/guide/quick-start)。

---

## 文档

在线文档：https://zhong-y-j.github.io/Hubloom/

| 想做什么 | 去哪 |
|----------|------|
| 了解定位与边界 | [文档首页](https://zhong-y-j.github.io/Hubloom/) · [Hubloom 是什么](https://zhong-y-j.github.io/Hubloom/#/guide/what-is-hubloom) |
| 5 分钟跑通 | [快速上手](https://zhong-y-j.github.io/Hubloom/#/guide/quick-start) |
| 接 API / 写 Skill | [接入 Swagger](https://zhong-y-j.github.io/Hubloom/#/usage/import-swagger) · [编写 Skill](https://zhong-y-j.github.io/Hubloom/#/usage/write-skill) |
| 查接口与配置 | [API 参考](https://zhong-y-j.github.io/Hubloom/#/reference/api-reference) · [配置项](https://zhong-y-j.github.io/Hubloom/#/reference/configuration) |
| 跑测试 | [测试计划](https://zhong-y-j.github.io/Hubloom/#/community/testing) |

---

## 路线图

### 已具备

- [x] OpenAPI → MCP 工具面；Policy-Bounded Typed ReAct 编排
- [x] Hubloom Serve（`/v1/chat`、history / resume；简洁 JSON SSE）
- [x] 演示前端；会话历史 SQLite / Postgres；Redis 挂起态与锁
- [x] Events / 企微回调已挂 Serve（按需开启）
- [x] 可选长期记忆、RAG、A2A MVP

### 下一步

- [ ] 高强度测试与文档持续对齐
- [ ] 事件驱动与 IM 增强（多通道、结果推送、卡片/表单）
- [ ] 体验与可观测（话术分层、指标、BFF 对接约定）

协议现状：MCP 已落地；产品 SSE 已落地；A2A 为双向 MVP。产品路径以 Markdown + Serve SSE 为准。

---

## 许可证

本项目基于 [Apache License 2.0](LICENSE) 开源发布。
