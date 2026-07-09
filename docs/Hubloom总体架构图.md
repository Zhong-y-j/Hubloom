# Hubloom 总体架构图

本文档描述 Hubloom 的系统分层与深度思考对话链路。在 VS Code、GitHub、Typora 中可预览 Mermaid 图。

---

## 1. 总览架构

三层结构：用户 → Hubloom → 外部系统。白底浅灰边框，无黄色分组背景。

```mermaid
%%{init: {"theme":"base","themeVariables":{"background":"#ffffff","primaryColor":"#ffffff","primaryBorderColor":"#cbd5e1","primaryTextColor":"#1e293b","secondaryColor":"#f8fafc","secondaryBorderColor":"#e2e8f0","tertiaryColor":"#f0fdfa","lineColor":"#64748b","clusterBkg":"#fafbfc","clusterBorder":"#e2e8f0","titleColor":"#475569","fontSize":"14px"}}}%%
flowchart LR
    UI["Web 对话页<br/><small>配置 · 聊天 · SSE</small>"]

    subgraph H[" "]
        direction TB
        H1["FastAPI 接入层"]
        H2["CortexAgent 编排"]
        H3["MCP 工具代理"]
        H1 --> H2 --> H3
    end

    LLM["LLM API"]
    SW["Swagger"]
    API["企业 REST API"]

    UI -->|"HTTP / SSE"| H1
    H2 -->|"快答 / 深思考"| LLM
    SW -->|"OpenAPI"| H1
    SW --> H3
    H3 -->|"Token + HTTP"| API

    classDef user fill:#eff6ff,stroke:#93c5fd,color:#1e3a5f
    classDef hub fill:#f0fdfa,stroke:#5eead4,color:#0f766e
    classDef ext fill:#f8fafc,stroke:#cbd5e1,color:#475569

    class UI user
    class H1,H2,H3 hub
    class LLM,SW,API ext
```

| 模块 | 作用 |
|------|------|
| Web 对话页 | 填写 API Key / Swagger；密钥仅存浏览器 |
| FastAPI | `/v1/chat`、`/v1/config/apply`、会话历史 |
| CortexAgent | Assessor 路由 → Chat 快答 / Thought 深思考 |
| MCP 层 | Swagger 转工具，代理调用企业 API |
| 外部系统 | LLM 推理、OpenAPI 文档、真实业务数据 |

---

## 2. Hubloom 内部展开

纵向主链路，扁平节点 + 配色区分，避免多层嵌套子图。

```mermaid
%%{init: {"theme":"base","themeVariables":{"background":"#ffffff","primaryColor":"#ffffff","primaryBorderColor":"#cbd5e1","primaryTextColor":"#1e293b","lineColor":"#94a3b8","fontSize":"13px"}}}%%
flowchart TB
    UI["Web UI"] --> API["FastAPI"]
    API --> RT["CortexRuntime"] --> AG["CortexAgent"] --> AS["Assessor"]

    AS -->|简单问答| CH["Chat"]
    AS -->|查数 · 调接口| TH["Thought"]

    CH --> LLM["LLM API"]
    TH --> LLM

    TH --> GW["MCP Gateway"] --> POOL["BackendPool"] --> WK["Workers"] --> REST["REST API"]

    AG <--> SQL[("SQLite 会话")]
    TH -.-> MEM["长期记忆 / RAG<br/>可选"]

    SW["Swagger"] --> API
    SW --> GW

    classDef entry fill:#eff6ff,stroke:#60a5fa,color:#1e40af
    classDef orch fill:#f0fdfa,stroke:#2dd4bf,color:#0f766e
    classDef mcp fill:#fff7ed,stroke:#fdba74,color:#9a3412
    classDef store fill:#f8fafc,stroke:#cbd5e1,color:#475569
    classDef ext fill:#fafafa,stroke:#d4d4d8,color:#52525b

    class UI,API entry
    class RT,AG,AS,CH,TH orch
    class GW,POOL,WK mcp
    class SQL,MEM store
    class LLM,SW,REST ext
```

---

## 3. 深度思考路径（时序图）

```mermaid
%%{init: {"theme":"base","themeVariables":{"background":"#ffffff","actorBkg":"#f8fafc","actorBorder":"#cbd5e1","actorTextColor":"#1e293b","signalColor":"#64748b","noteBkgColor":"#f0fdfa","noteBorderColor":"#99f6e4"}}}%%
sequenceDiagram
    autonumber
    actor U as 用户
    participant F as FastAPI
    participant A as CortexAgent
    participant T as Thought
    participant G as MCP Gateway
    participant R as REST API
    participant L as LLM

    U->>F: 发送消息
    F->>A: 创建 Agent · 读历史
    A->>L: 路由 → Thought

    T->>L: 推理
    T->>G: call_tool
    G->>R: HTTP
    R-->>G: JSON
    G-->>T: 结果
    T->>L: 组织回复

    T-->>F: SSE
    F-->>U: 思考 + 回答
    A->>A: 保存会话
```

### 说明

- **Chat 快答**：不经过 MCP，直接 LLM 回复。
- **Thought 深思考**：经 MCP Gateway → Worker → 企业 API。
- SSE 事件：`thought_delta` · `tool_call` · `text_delta` · `turn_complete`

---

## 模块详解

- [ADP 编排层](./Hubloom-ADP编排.md) — 路由决策、Chat / Thought 双路径
- [MCP 适配层](./Hubloom-MCP适配.md) — Swagger → 工具、网关与 Worker、Token 透传
- [A2A 互联](./Hubloom-A2A互联.md) — 双向 A2A 设计：入站 Server / 出站 Client（设计稿）
- [工具层](./Hubloom-工具层.md) — BaseTool / Registry / Runner 与内置工具
- [记忆系统](./Hubloom-记忆系统.md) — 会话 / 长期记忆 / 离线提炼
- [RAG 知识库](./Hubloom-RAG知识库.md) — 文档入库 / 向量检索 / search_documents

---

## 导出高清图

预览仍不满意时，可复制代码到 [Mermaid Live Editor](https://mermaid.live) 导出 SVG/PNG。
