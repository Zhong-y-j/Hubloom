# Hubloom

如果说 Spring Boot 是后端接口的「地基」，Vue Admin 是后台页面的「脚手架」，那 **Hubloom 就是 AI Agent 时代的基座脚手架**。

它不是一个独立的聊天机器人，而是一层让**现有业务系统**长出 AI 手脚的胶水：接上你现有的 Swagger/OpenAPI 文档，Agent 就能在真实 API 上完成「决策 → 调工具 / 追问 / 确认 → 收工」。回复用 Markdown；网页可挂起等人（interactive），企微等入口用跨轮交班。**业务逻辑依然留在你的系统里，Hubloom 只做「翻译」和「路由」。**

**你主要做：** 配 LLM 与 Swagger、写 Skill（含可选 Playbook）、按需定制前端或嵌入门户。  
**底座替你搞定：** 工具调用（MCP）、Typed ReAct 编排、SSE 流式回合、会话记忆、鉴权透传与过程可观测。

交付分两层：**Hubloom Serve**（`src/server/` / `main.py`）产品 API；**演示前端**（`examples/chat/web`）开箱对话。记忆、RAG、A2A、事件 Webhook、企微入口等为可选能力，默认不挡主路径。

协议要点：**MCP** 把 HTTP 变成工具；产品出站为**简洁 JSON SSE**（非 A2UI / AG-UI）。完整手册见 [docs/](./docs/)（Docsify）。

## 特性

- **嵌入式智能，而非旁路助手**：智能体站在流程与数据平面上办事，直接触达企业 API，结果可核对、过程可复盘
- **契约即能力**：OpenAPI/Swagger 动态映射工具面，换业务域主要换配置，快速复用存量数字化资产
- **Policy-Bounded Typed ReAct**：单环 Decide → Gate → `act` / `ask` / `await_confirm` / `finish`；Skill Playbook 可硬拦
- **Wait Profile**：网页 `interactive` 挂起续跑；企微等 `turn_based` 跨轮；事件入口可 `no_wait`
- **Markdown 体验**：结论与过程用 Markdown；工具调用可展开复盘（演示前端无 A2UI 面板）
- **从建议到闭环**：经 MCP 元工具调用真实 REST，把「能说会道」变成「能做完事」
- **可演进的运营智能**：配置 + Skill 固化领域 Know-how；记忆与 RAG 沉淀上下文；A2A 支撑多智能体协同
- **事件 / 企微入口**：模块已具备；按部署接到 Serve 或独立进程
- **过程可审计**：轨迹、工具链与 SSE 事件可上屏、可复盘

---

## 界面预览

对话办事：自然语言驱动 MCP 工具，Markdown 呈现结论（工具调用过程可展开查看）。

![对话与交互面板](./docs/assets/hubloom-chat-a2ui-panel.png)

创建完成后用表格核对系统状态（工具调用过程可展开查看）。

![结果核对](./docs/assets/hubloom-chat-result-tables.png)

## 架构文档

Hubloom Serve 负责产品 HTTP API；`examples/chat/web` 负责开箱演示前端；Runtime（`HubloomRuntime`）可嵌入门户与自有应用。

**本地预览文档站（Docsify，与 Hello-Agents 同类）：**

```bash
npx --yes serve docs -p 3000
```

浏览器打开 `http://127.0.0.1:3000`。文档按学习路径组织：

| 部分 | 说明 |
|------|------|
| [文档首页](./docs/README.md) | Docsify 入口 |
| [入门指南](./docs/guide/README.md) | 是什么、安装、快速上手、第一个 Skill |
| [核心概念](./docs/core-concepts/README.md) | 架构与 MCP / A2UI / AG-UI / Skill |
| [使用指南](./docs/usage/README.md) | 配 LLM、接 Swagger、写 Skill、定制与嵌入 |
| [进阶功能](./docs/advanced/README.md) | 记忆、RAG、A2A、事件、企微 |
| [参考文档](./docs/reference/README.md) | API、配置项、FAQ |
| [社区](./docs/community/README.md) | 贡献与更新日志 |

---

## 快速开始

### 环境要求

- Python 3.12+
- [uv](https://github.com/astral-sh/uv)（推荐）或 pip
- Node.js（仅跑示例站前端时需要）

### 1. 安装依赖

```bash
uv sync
```

或使用 pip：

```bash
pip install -r requirements.txt
```

### 2. 配置

```bash
cp config/env.example.yaml config/env.yaml
```

在 `config/env.yaml` 中填写 LLM 与 MCP（OpenAPI 规格、业务 API 地址等）。业务 Token 由前端会话传入，不要写进配置文件。

### 3. 启动 Hubloom Serve + 演示前端

```bash
# 产品 API（默认 :8765，见 config http.port）
PYTHONPATH=src uv run python main.py
# 或：PYTHONPATH=src uv run python -m server serve --config config/env.yaml

# 前端（另开终端）
cd examples/chat/web && npm install && npm run dev
```

- **Web 对话页**：http://127.0.0.1:5173/（Vite 代理 `/v1` → Serve）
- **API 文档**：http://127.0.0.1:8765/docs

**健康检查**

```bash
curl http://127.0.0.1:8765/health
```

**调用对话接口**

```bash
curl -s http://127.0.0.1:8765/v1/chat \
  -H "Content-Type: application/json" \
  -H "X-Session-Id: demo-session" \
  -H "X-MCP-Token: your-business-token" \
  -d '{"message":"你好，你能做什么？","stream":false,"wait_profile":"interactive"}'
```

默认 SSE（`"stream": true`）。历史：`GET /v1/chat/history?session_id=demo-session`。  
网页对话缺参时走 `POST /v1/chat/resume`（interactive 挂起续跑）。

**事件入站 / 企业微信**

契约见 **[事件 Webhook](./docs/advanced/webhook.md)**、**[企业微信入口](./docs/advanced/wecom-integration.md)**。  
当前产品 Serve 以对话 API 为主；Events / 企微回调可后续迁入 `src/server/`（联调脚本见 `tests/test_im_wecom.py`）。

---

## 路线图

### 当前版本（重构后）

- [x] OpenAPI → MCP 工具面（catalog + 元工具 `list_api` / `call_api`）
- [x] **Policy-Bounded Typed ReAct** 单环（Decide → Gate → Act / Ask / AwaitConfirm / Finish）
- [x] Evidence Journal + Wait Profile（`interactive` / `turn_based` / `no_wait`）
- [x] **Hubloom Serve** 产品 HTTP API（简洁 SSE，无 A2UI / AG-UI）
- [x] 演示前端：Markdown 对话 + interactive 挂起续跑
- [x] 多轮会话与工具链感知的历史裁剪
- [x] 可选长期记忆与 RAG 知识库
- [x] **A2A 双向 MVP**：入站 Server、出站 `list_agents` / `delegate_task`
- [x] **事件驱动 Webhook MVP**（模块在 `src/events/`；入口接线按部署演进）
- [x] **企微对话入口 MVP**（模块在 `src/im/wecom/`；入口接线按部署演进）

### 下一步

- [ ] **事件驱动增强**：消息队列 / 定时告警入站、结果回调完善、打开会话时主动推屏（非仅刷新历史）
- [ ] **IM 增强**：事件结果推企微、钉钉 / 飞书 / Slack、企微内表单/卡片
- [ ] **自动化运营增强**：在配置 + Skill 之上强化流程编排与无人值守执行，向自主运营与多智能体协同再进一步
- [ ] **文档对齐**：总体架构图 / ADP 编排文档与 Think–Present–Respond、元工具单轨表述一致
- [ ] **A2A 增强**：链式委托、动态发现、正式凭证 Provider
- [ ] **AG-UI 增强**：更完整的官方事件面（如独立 THINKING 事件族）、与第三方 AG-UI 客户端互操作验证
- [ ] **可观测与运维**：更完整的出站指标与部署约定

### 协议栈演进

| 协议      | 角色                               | 状态                                  |
| --------- | ---------------------------------- | ------------------------------------- |
| **MCP**   | Agent ↔ 企业 API / 数据            | 已落地                                |
| **A2A**   | Agent ↔ Agent 委托                 | 双向 MVP                              |
| **A2UI**  | 声明式生成式 UI（表单等）          | 已落地（经 AG-UI CUSTOM / 面板）      |
| **AG-UI** | Agent ↔ 用户应用的标准交互事件协议 | 已落地（出站 SSE + 表单 action 回传） |
| **ANP**   | 更开放的 Agent 互联                | 探索中                                |

> **A2UI ≠ AG-UI**：A2UI 描述「画什么界面」；AG-UI 描述「Agent 与前端如何用标准事件对话」。二者互补，可叠加使用。

---

## 许可证

本项目基于 [Apache License 2.0](LICENSE) 开源发布。
