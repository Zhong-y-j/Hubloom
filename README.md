# Agent Cortex（灵枢）

**OpenAPI 驱动的 MCP 智能体中枢** — 传入 Swagger/OpenAPI，启动 MCP 服务，通过对话调用后端 API，为用户提供自然语言智能服务。

中文名 **灵枢**：位于用户与业务 API 之间的调度层，负责理解意图、调用工具、汇总结果。默认以 **ReAct + MCP** 为主路径；复杂多步编排（Plan / Reflection）作为可选进阶能力保留在仓库中。

> 详细设计与演进路线见 [`设计思路.md`](设计思路.md)。

---

## 特性

- **Swagger → MCP**：基于 [FastMCP](https://github.com/PrefectHQ/fastmcp) 从 OpenAPI/Swagger 动态生成 MCP 工具，换 API 只需改环境变量
- **ReAct 主路径**：澄清需求、查询列表、调用写接口、解释业务错误（403/400 等），均在 ReAct 工具循环内完成
- **Hub 轻量编排**：路由、多轮会话、执行结果写入对话历史
- **通用 MCP 设计**：工具目录、参数提示、Plan 提示词均来自运行时 schema，不绑定某一固定业务或 Swagger
- **可选能力**：PlanExecute（多步计划与 Gate B 校验）、Reflection（审查与修订重跑）、Memory / RAG（env 配置启用）

---

## 架构概览

```
用户
  │
  ▼
Hub（路由 · 会话 · 回复汇总）
  │
  ▼
ReAct（默认）────── MCP Server ← OpenAPI / Swagger
  │                      │
  │                      ▼
  │                 业务 REST API
  │
  └─► [可选] Plan → Execute → Reflection
```

| 模块 | 默认 | 说明 |
|------|------|------|
| **ReAct** | ✅ 启用 | 流式 LLM + MCP 工具循环，日常对话与 API 调用 |
| **Hub** | ✅ 启用 | `clarify_only` / `direct_reply` /（可选）`plan_execute` |
| **Plan + Execute** | 按需 | 显式多步编排、步骤依赖、组参、执行前缺参拦截 |
| **Reflection** | 按需 | 审查 deliverable，支持修订重跑 |
| **Memory / RAG** | 按需 | 长期记忆、知识库检索（需配置 Neo4j / Qdrant 等） |

**推荐用法**：开源快速体验与多数业务场景使用 **ReAct + Hub + MCP** 即可；当任务固定为多步流水线、需要 step trace 或自动补跑时，再启用 Plan / Reflection。

---

## 快速开始

### 环境要求

- Python 3.12+
- [uv](https://github.com/astral-sh/uv)（推荐）或 pip

### 1. 安装依赖

**推荐（与 `uv.lock` 一致）：**

```bash
uv sync
```

**或使用 pip：**

```bash
pip install -r requirements.txt
```

### 2. 配置环境变量

```bash
cp .env.example .env
# 编辑 .env，至少填写 OPENAI_API_KEY；对接业务 API 时填写 MCP_* 
```

最小可运行配置（无需 Qdrant / Neo4j）：

```bash
OPENAI_API_KEY=sk-...
CORTEX_ENABLE_LONG_TERM_MEMORY=0
MCP_SWAGGER_URL=https://your-api.example.com/swagger/v1/swagger.json
MCP_BASE_URL=https://your-api.example.com
```

完整变量说明见 [`.env.example`](.env.example) 与下方配置表。

未配置 `MCP_SWAGGER_URL` 时，MCP 子进程会回退到 Petstore 示例 spec。

### 3. 启动对话 REPL

```bash
PYTHONPATH=. uv run python main.py
```

同一 `session_id` 下 ReAct 会加载上一轮对话历史；Plan 执行完成的摘要也会写入会话存储（若已配置 `data/memory.db`）。

### 4. 启动 HTTP API（企业后端 / 前端 BFF 对接）

```bash
PYTHONPATH=. uv run python server.py
# 或
PYTHONPATH=. uv run uvicorn agents.api.app:app --host 0.0.0.0 --port 8000
```

可选环境变量：`CORTEX_API_HOST`、`CORTEX_API_PORT`（默认 `0.0.0.0:8000`）。

**健康检查**

```bash
curl http://127.0.0.1:8000/health
```

**非流式对话**

```bash
curl -s http://127.0.0.1:8000/v1/chat \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer <用户或网关 Token>" \
  -H "X-Session-Id: user-001-conv-abc" \
  -d '{"message":"帮我查最近订单","stream":false}'
```

**SSE 流式**（`stream: true` 默认）：响应 `text/event-stream`，事件类型包括 `text_delta`、`tool_call`、`tool_result`、`phase`、`turn_complete`、`error`。

企业接入建议：**前端 → 企业后端（验 JWT）→ 本 API**，Header 透传 `Authorization`；`session_id` 可通过 body 或 `X-Session-Id` 指定。当前 MCP 下游仍使用 `.env` 的 `MCP_TOKEN`（按请求 Token 透传至 MCP 为后续扩展）。

交互式文档：启动后访问 `http://127.0.0.1:8000/docs`。**对话页面**：`http://127.0.0.1:8000/`。

### 5. 运行测试

```bash
uv run python -m unittest tests.test_param_readiness tests.test_transport_errors tests.test_api_events -v
```

---

## 工作流程（默认 ReAct 路径）

1. 用户输入自然语言需求
2. **ReAct** 结合 MCP 工具目录（name / description / parameters）澄清或调用 API
3. 读操作（列表、详情）优先用于补全 ID 与可选项；写操作在参数齐备且用户确认后调用
4. **Hub** 输出 `direct_reply` 或 `clarify_only`，将结果展示给用户
5. 多轮对话从 SQLite 会话历史继续

当 ReAct 输出 `general_task` 且未标记 `react_tool_done` 时，Hub 会进入 **Plan → Execute →（可选）Reflection** 管线（当前实测中多数任务在 ReAct 内即可完成）。

---

## 项目结构（摘要）

```
agents/
  react/          # ReAct 意图澄清 + MCP 工具循环（默认执行引擎）
  hub/            # 中枢路由与回复组合
  plan/           # [可选] PlanExecute、组参、Gate B
  reflection/     # [可选] 质量审查与修订建议
  app/bootstrap.py
mcp_adapter/      # OpenAPI → MCP 子进程（FastMCP）
tools/            # ToolRegistry、param_hints、transport_errors
memory/           # 会话存储、长期记忆（可选）
retrieval/        # 知识库 RAG（可选）
main.py           # Hub REPL 入口
```

---

## 配置说明

| 变量 | 说明 |
|------|------|
| `MCP_SWAGGER_URL` | OpenAPI / Swagger 文档 URL 或本地路径 |
| `MCP_BASE_URL` | 下游 API 根地址（spec 无法推断时必填） |
| `MCP_TOKEN` | 调用下游 API 的 Bearer Token |
| `OPENAI_API_KEY` | LLM API Key |
| `OPENAI_BASE_URL` / `OPENAI_MODEL` | 兼容网关与模型名 |
| `HUB_MAX_REVISION_ROUNDS` | Reflection 修订重跑轮数（默认 `1`） |
| `NEO4J_*` / `QDRANT_*` | 长期记忆与向量库（可选，未配置时可仅用 SQLite 会话） |
| `CORTEX_AGENT_LOG` | 开启 Agent / MCP 调试日志 |
| `CORTEX_API_HOST` / `CORTEX_API_PORT` | HTTP 服务监听地址（默认 `0.0.0.0:8000`） |
| `CORTEX_DEFAULT_SESSION_ID` | 未传 session 时的默认 namespace（默认 `mem:tester_id:default`） |
| `CORTEX_SESSION_ID_TEMPLATE` | 短 session 键套入模板（默认 `mem:{session_id}:default`） |
| `CORTEX_MEMORY_DB` | SQLite 会话库路径（默认 `data/memory.db`） |
| `CORTEX_KB_DIR` | 知识库向量索引持久化目录（Chroma；默认 `data/knowledge_db`） |
| `CORTEX_RAG_DOCS` | RAG 源文档路径（逗号分隔文件或目录）；配置后自动开启 RAG 并在 Hub 启动时入库 |
| `CORTEX_ENABLE_RAG` | 可选：`0` 强制关闭 RAG；`1` 在无文档路径时仅启用已有索引检索 |
| `CORTEX_ENABLE_LONG_TERM_MEMORY` | 是否启用长期记忆（Qdrant episodic/semantic + Neo4j associative；默认 `true`） |

后续计划在 env 中补充：`ENABLE_PLAN`、`ENABLE_REFLECTION`、MCP 工具 tag 过滤等，便于上百接口场景下控制暴露给 LLM 的工具集。

---

## 与同类项目的关系

- **Swagger → MCP**：与 FastMCP、openapi-mcp、openapi-to-mcp 等同类；本项目使用 FastMCP 并针对 HTTP 状态、业务错误做了适配
- **MCP + Agent**：与 mcp-agent、IDE + MCP 类似；差异在于提供 Hub、可选 Plan/Reflection、会话与记忆集成
- **定位**：不是「又一个 OpenAPI 转 MCP 工具」，而是 **可对接任意 OpenAPI 的对话式 API 智能服务框架**

---

## 路线图

- [x] OpenAPI → MCP（FastMCP）
- [x] ReAct 全 MCP 工具调用 + 参数澄清提示
- [x] Hub 多轮会话与 Plan 结果写入历史
- [ ] env 开关：默认 ReAct-only，Plan/Reflection 可选
- [ ] MCP 工具过滤（按 tag / 数量限制），适配大型 Swagger
- [x] 完善 `.env.example` 与部署文档
- [ ] 企业集成：JWT / SSO 透传、多租户、审计日志（插件或扩展层）

---

## 开源与贡献

欢迎 Issue 与 PR。企业级鉴权、工作流持久化等能力将按「核心开源 + 扩展可选」方式演进，避免把 JWT、SSO 等强绑定逻辑塞进默认路径。

---

## 许可证

见仓库根目录 `LICENSE`（若尚未添加，开源发布前请补充）。
