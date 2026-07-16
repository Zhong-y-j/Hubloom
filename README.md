# Hubloom

**Hubloom 是面向企业的开源 Agentic Runtime：对接企业级数据与客户自有数据，将存量业务能力沉淀为可编排智能服务，支撑任务拆解、工具调用、流程优化与决策支持。**

> 目标不是旁路聊天机器人，而是**业务嵌入型智能服务**——智能体直接嵌入企业既有流程与数据平面，在真实系统上自主完成「理解目标 → 拆解任务 → 调用工具 → 优化路径 → 反馈结果」。以 OpenAPI/Swagger 为契约，连通 ERP / CRM / 运营中台等企业 API 与客户私有数据；经评估路由在快答与深度推理间自适应分流；全程可观测、可审计地触达真实业务接口。叠加会话记忆、长期记忆与 RAG，让系统具备持续上下文与知识沉淀能力，逐步走向**可自主决策、可持续学习**的自动化运营与智能推荐。多业务域可各自实例化为 Agent，再通过 A2A 组成跨系统协作网络。

**MCP** 贯通企业 API、运营数据与客户自有数据；**A2A** 支撑 Agent 入站承接与出站委托（过程可上屏、结果回馈编排）；**ANP** 仍在路线图中。

## 特性

- **业务嵌入，数据贯通**：对接企业级 API 与客户自有数据，智能服务长在流程里，而不是漂在业务外
- **任务拆解与工具调用**：将复杂目标分解为可执行步骤，经 MCP 精准调用真实 REST 能力，闭环落地而非空谈建议
- **契约驱动工具化**：从 OpenAPI/Swagger 动态构建工具面，切换业务系统只需更新配置
- **流程优化与自动化运营**：自适应双路径编排——轻量问答走快答，复杂业务走深度推理，持续压缩人工流转成本
- **智能推荐与决策支持**：基于真实返回、会话上下文与可选知识库，提供可追溯的推荐与决策辅助
- **自主决策与持续学习**：多智能体协同（A2A）承接与委托任务；记忆与 RAG 沉淀经验，支撑可演进的运营智能
- **可解释与可审计**：完整呈现推理轨迹与工具调用链，结果可核对、过程可复盘

---

## 架构文档

用户侧对话入口 → **ADP 智能编排**（任务拆解 / 快答 / 深思考）→ **MCP**（OpenAPI → 企业数据与业务能力）与 **A2A**（跨 Agent 协同）并列；可选**长期记忆**与 **RAG** 支撑持续学习。各层详见 [docs/](./docs/)：

| 文档                                      | 说明                                       |
| ----------------------------------------- | ------------------------------------------ |
| [总体架构图](./docs/Hubloom总体架构图.md) | 系统分层、MCP / A2A 展开与时序             |
| [ADP 编排](./docs/Hubloom-ADP编排.md)     | Assessor 路由、Chat / Thought 双路径       |
| [MCP 适配](./docs/Hubloom-MCP适配.md)     | OpenAPI 管线、Gateway / Worker、Token 透传 |
| [A2A 互联](./docs/Hubloom-A2A互联.md)     | 双向 A2A、双通道 UI、防环与联调            |
| [工具层](./docs/Hubloom-工具层.md)        | ToolRegistry、ToolRunner 与内置工具        |
| [记忆系统](./docs/Hubloom-记忆系统.md)    | 会话 / 长期记忆、Handler 层、离线提炼      |
| [RAG 知识库](./docs/Hubloom-RAG知识库.md) | 文档入库、向量检索、`search_documents`     |

---

## 快速开始

### 环境要求

- Python 3.12+
- [uv](https://github.com/astral-sh/uv)（推荐）或 pip

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

### 3. 启动服务

```bash
PYTHONPATH=. uv run python main.py
```

默认监听 `http://127.0.0.1:8000`。可通过 `CORTEX_API_HOST`、`CORTEX_API_PORT` 调整。

### 4. 开始对话

- **Web 对话页**：http://127.0.0.1:8000/
- **API 文档**：http://127.0.0.1:8000/docs

**健康检查**

```bash
curl http://127.0.0.1:8000/health
```

**调用对话接口**

```bash
curl -s http://127.0.0.1:8000/v1/chat \
  -H "Content-Type: application/json" \
  -H "X-Session-Id: demo-session" \
  -H "X-MCP-Token: your-business-token" \
  -d '{"message":"你好，你能做什么？","stream":false}'
```

默认开启 SSE 流式（`"stream": true`）。生产接入时，建议由业务后端验签后转发请求，并透传 `Authorization`（或 `X-MCP-Token`）与 `X-Session-Id`。

---

## 路线图

### 当前版本

- [x] OpenAPI → MCP 工具生成
- [x] 评估路由 → 快答 / 深度思考双路径
- [x] HTTP API、SSE 流式与 Web 对话页
- [x] 多轮会话（SQLite）
- [x] 可选长期记忆与 RAG 知识库
- [x] **MCP 适配层**：Gateway + Worker 按 tag 分组、工具过滤
- [x] **A2A 双向 MVP**：入站 Server、出站 `list_agents` / `delegate_task`、远程过程上屏、入站防环

### 下一步

- [ ] **A2A 增强**：链式委托（如 A2→A3）、动态发现、正式凭证 Provider
- [ ] **可观测与运维**：更完整的出站指标与部署约定

### 协议栈演进

- [x] **MCP** — 连接企业 API 与数据
- [x] **A2A** — 跨 Agent 任务委托（双向 MVP）
- [ ] **ANP** — 更开放的 Agent 互联与协作（探索中）

---

## 许可证

本项目基于 [Apache License 2.0](LICENSE) 开源发布。
