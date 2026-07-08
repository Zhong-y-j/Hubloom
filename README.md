# Hubloom

**Hubloom 是一个开源的企业智能体互联与编排平台**

> 给企业现有 REST 后台接一层自然语言入口：用户用对话的方式查数据、调接口，而无需改动原有业务系统。传入 Swagger/OpenAPI 即可自动生成可调用的工具集；经评估路由分流为快答 / 深度思考两条路径，安全、可解释地调用企业 API，并支持会话历史及可选的记忆与 RAG 增强。

Hubloom 不仅是「用自然语言操作 API」，更是企业智能体技术栈中的**编排与互联枢纽**。**MCP** 负责连接工具与数据（当前已支持）；**A2A**、**ANP** 在路线图中，分别用于跨 Agent 任务委托与更开放的 Agent 互联协作。

---

## 特性

- **Swagger → MCP**：从 OpenAPI/Swagger 动态生成工具，换一套 API 只需改环境变量
- **双路径编排**：评估路由后自动分流——简单问答走快答，查数/调接口走深度思考
- **真实 API 调用**：深度思考路径通过 MCP 调用企业 REST API，基于真实返回作答，不编造业务数据
- **可解释执行**：展示推理与工具调用过程，回复可追溯、可核对
- **会话与增强**：多轮对话历史；可选长期记忆与 RAG 知识库

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

### 2. 配置环境变量

```bash
cp .env.example .env
```

至少填写 `OPENAI_API_KEY`；对接业务 API 时配置 `MCP_*`：

```bash
OPENAI_API_KEY=sk-...
OPENAI_MODEL=...
OPENAI_BASE_URL=...
MCP_SWAGGER_URL=https://your-api.example.com/swagger/v1/swagger.json
MCP_BASE_URL=https://your-api.example.com
MCP_TOKEN=your-token
```

完整变量见下方 [配置说明](#配置说明)。

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
  -d '{"message":"你好，你能做什么？","stream":false}'
```

默认开启 SSE 流式（`"stream": true`）。生产接入时，建议由业务后端验签后转发请求，并透传 `Authorization` 与 `X-Session-Id`。

---

## 配置说明

复制 [`.env.example`](.env.example) 为 `.env` 后按需修改。下表按用途分组，未列出的可选变量以 `.env.example` 为准。

### LLM

| 变量                     | 说明                                                 |
| ------------------------ | ---------------------------------------------------- |
| `OPENAI_API_KEY`         | LLM API Key（必填）                                  |
| `OPENAI_MODEL`           | 模型名称                                             |
| `OPENAI_BASE_URL`        | 兼容 OpenAI 的网关地址                               |
| `OPENAI_TIMEOUT`         | 请求超时（秒，默认 `180`）                           |
| `OPENAI_EMBEDDING_MODEL` | 嵌入模型（RAG / 长期记忆，默认 `text-embedding-v3`） |

### MCP / 业务 API

| 变量              | 说明                                   |
| ----------------- | -------------------------------------- |
| `MCP_SWAGGER_URL` | OpenAPI / Swagger 文档 URL 或本地路径  |
| `MCP_BASE_URL`    | 下游 API 根地址（spec 无法推断时必填） |
| `MCP_TOKEN`       | 调用下游 API 的 Token                  |
| `MCP_AUTH_SCHEME` | 认证前缀：`Bearer`（默认）或 `JWT`     |

未配置 `MCP_SWAGGER_URL` 时使用 Petstore 示例 spec。

### 会话与存储

| 变量                           | 说明                                                     |
| ------------------------------ | -------------------------------------------------------- |
| `CORTEX_DEFAULT_SESSION_ID`    | 未传 session 时的默认 namespace                          |
| `CORTEX_SESSION_ID_TEMPLATE`   | 短 session 键套入模板（默认 `mem:{session_id}:default`） |
| `CORTEX_MEMORY_DB`             | SQLite 对话历史路径（默认 `data/memory.db`）             |
| `CORTEX_CONSOLIDATE_MIN_TURNS` | 满 N 轮用户消息后触发离线记忆提炼（默认 `3`）            |

### RAG 知识库（可选）

| 变量                | 说明                                                 |
| ------------------- | ---------------------------------------------------- |
| `CORTEX_RAG_DOCS`   | 源文档路径，逗号分隔文件或目录；配置后启动时自动入库 |
| `CORTEX_ENABLE_RAG` | `0` 强制关闭；`1` 在无文档路径时仅启用已有索引检索   |
| `CORTEX_KB_DIR`     | 向量索引持久化目录（默认 `data/knowledge_db`）       |

### 长期记忆（可选）

| 变量                                                             | 说明                                                 |
| ---------------------------------------------------------------- | ---------------------------------------------------- |
| `CORTEX_ENABLE_LONG_TERM_MEMORY`                                 | `1` 开启 Qdrant + Neo4j 长期记忆；`0` 仅 SQLite 会话 |
| `QDRANT_URL` / `QDRANT_API_KEY` / `QDRANT_COLLECTION`            | Qdrant 向量库                                        |
| `NEO4J_URI` / `NEO4J_USER` / `NEO4J_PASSWORD` / `NEO4J_DATABASE` | Neo4j 图记忆                                         |
| `NEO4J_SKIP_DNS_CHECK`                                           | `1` 跳过 Neo4j DNS 检查                              |

### HTTP 服务

| 变量                | 说明                       |
| ------------------- | -------------------------- |
| `CORTEX_API_HOST`   | 监听地址（默认 `0.0.0.0`） |
| `CORTEX_API_PORT`   | 监听端口（默认 `8000`）    |
| `CORTEX_API_RELOAD` | `1` 开启开发热重载         |

### 日志

| 变量                | 说明                                             |
| ------------------- | ------------------------------------------------ |
| `CORTEX_AGENT_LOG`  | 开启 Agent / MCP 调试日志                        |
| `CORTEX_CORTEX_LOG` | 仅 ADP 编排日志（未设时跟随 `CORTEX_AGENT_LOG`） |
| `CORTEX_MEMORY_LOG` | 仅记忆链路日志（未设时跟随 `CORTEX_AGENT_LOG`）  |
| `CORTEX_LOG_FILE`   | 日志文件路径（默认 `logs/debug.log`）            |

---

## 路线图

### 当前版本

- [x] OpenAPI → MCP 工具生成
- [x] 评估路由 → 快答 / 深度思考双路径
- [x] HTTP API、SSE 流式与 Web 对话页
- [x] 多轮会话（SQLite）
- [x] 可选长期记忆与 RAG 知识库

### 近期

- [x] **MCP 适配层重构**：统一 API 响应结构处理，精简 FastMCP 集成方式，提升可维护性
- [x] **MCP 工具过滤**：按 tag 或数量限制暴露工具，适配大型 Swagger

### 协议栈演进

- [x] **MCP** — 连接企业 API 与数据
- [ ] **A2A** — 跨系统 Agent 任务委托
- [ ] **ANP** — 更开放的 Agent 互联与协作（探索中）

---

## 许可证

本项目基于 [Apache License 2.0](LICENSE) 开源发布。
