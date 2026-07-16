# Hubloom 总体架构图

本文档描述 Hubloom 的系统分层与主对话 / A2A 链路。在 VS Code、GitHub、Typora 中可预览 Mermaid 图。

---

## 1. 总览架构

用户与外部 Agent 均可进入 Hubloom；对内走 MCP 调企业 API，对外可作 A2A Server / Client。

```mermaid
%%{init: {"theme":"base","themeVariables":{"background":"#ffffff","primaryColor":"#ffffff","primaryBorderColor":"#cbd5e1","primaryTextColor":"#1e293b","secondaryColor":"#f8fafc","secondaryBorderColor":"#e2e8f0","tertiaryColor":"#f0fdfa","lineColor":"#64748b","clusterBkg":"#fafbfc","clusterBorder":"#e2e8f0","titleColor":"#475569","fontSize":"14px"}}}%%
flowchart LR
    UI["Web 对话页<br/><small>配置 · 聊天 · SSE</small>"]
    EA["外部 A2A Client<br/><small>其他 Agent</small>"]
    RA["远程 A2A Server<br/><small>被委托 Agent</small>"]

    subgraph H["Hubloom"]
        direction TB
        H1["FastAPI 接入层<br/><small>/v1/chat · A2A · Card</small>"]
        H2["CortexAgent 编排"]
        H3["MCP 工具代理"]
        H4["A2A Client<br/><small>list_agents · delegate_task</small>"]
        H1 --> H2
        H2 --> H3
        H2 --> H4
    end

    LLM["LLM API"]
    SW["Swagger"]
    API["企业 REST API"]

    UI -->|"HTTP / SSE"| H1
    EA -->|"A2A 入站"| H1
    H2 -->|"快答 / 深思考"| LLM
    SW -->|"OpenAPI"| H1
    SW --> H3
    H3 -->|"Token + HTTP"| API
    H4 -->|"A2A 出站"| RA

    classDef user fill:#eff6ff,stroke:#93c5fd,color:#1e3a5f
    classDef hub fill:#f0fdfa,stroke:#5eead4,color:#0f766e
    classDef a2a fill:#ecfdf5,stroke:#2dd4bf,color:#0f766e
    classDef ext fill:#f8fafc,stroke:#cbd5e1,color:#475569

    class UI,EA user
    class H1,H2,H3 hub
    class H4,RA a2a
    class LLM,SW,API ext
```

| 模块 | 作用 |
|------|------|
| Web 对话页 | 填写 API Key / Swagger；密钥仅存浏览器；展示工具与远程过程 |
| FastAPI | `/v1/chat`、`/v1/mcp/status`、会话历史、**A2A 路由与 Agent Card** |
| CortexAgent | Assessor 路由 → Chat 快答 / Thought 深思考；入站 A2A 复用同一编排 |
| MCP 层 | Swagger 转工具，代理调用企业 API |
| A2A Client | Thought 工具 `list_agents` / `delegate_task` → 远程 Agent |
| 外部系统 | LLM、OpenAPI、企业 REST、远程 A2A Server |

---

## 2. Hubloom 内部展开

纵向主链路：编排之下并列 **MCP（调 API）** 与 **A2A（调 Agent）**。

```mermaid
%%{init: {"theme":"base","themeVariables":{"background":"#ffffff","primaryColor":"#ffffff","primaryBorderColor":"#cbd5e1","primaryTextColor":"#1e293b","lineColor":"#94a3b8","fontSize":"13px"}}}%%
flowchart TB
    UI["Web UI"] --> API["FastAPI<br/>/v1/chat"]
    EXT["外部 A2A Client"] --> A2AS["A2A Server<br/>Card · Executor · bridge"]
    A2AS --> RT
    API --> RT["CortexRuntime"] --> AG["CortexAgent"] --> AS["Assessor"]

    AS -->|简单问答| CH["Chat"]
    AS -->|查数 · 调接口 · 跨 Agent| TH["Thought"]

    CH --> LLM["LLM API"]
    TH --> LLM

    TH --> TOOLS["ToolRegistry<br/>元工具 list_tools / call_tool"]
    TOOLS --> WK["全量 MCP worker"] --> REST["REST API"]
    TOOLS --> A2AC["A2A Client<br/>registry · transport"] --> RA["远程 A2A Agent"]

    AG <--> SQL[("SQLite 会话")]
    TH -.-> MEM["长期记忆 / RAG<br/>可选"]

    SW["Swagger"] --> CAT["API catalog → prompt"]
    SW --> WK
    CAT --> TH
    SW -.->|"tag → skills"| A2AS

    classDef entry fill:#eff6ff,stroke:#60a5fa,color:#1e40af
    classDef orch fill:#f0fdfa,stroke:#2dd4bf,color:#0f766e
    classDef mcp fill:#fff7ed,stroke:#fdba74,color:#9a3412
    classDef a2a fill:#ecfdf5,stroke:#14b8a6,color:#0f766e
    classDef store fill:#f8fafc,stroke:#cbd5e1,color:#475569
    classDef ext fill:#fafafa,stroke:#d4d4d8,color:#52525b

    class UI,API,EXT entry
    class RT,AG,AS,CH,TH,TOOLS orch
    class GW,POOL,WK mcp
    class A2AS,A2AC,RA a2a
    class SQL,MEM store
    class LLM,SW,REST ext
```

---

## 3. 深度思考路径（时序图 · MCP）

用户经 Thought 调企业 API 的典型路径：

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

---

## 4. 跨 Agent 路径（时序图 · A2A）

用户经 Thought **出站委托**；过程双通道上屏，短 answer 回 LLM。入站时禁止再 `delegate_task`（防环）。

```mermaid
%%{init: {"theme":"base","themeVariables":{"background":"#ffffff","actorBkg":"#f8fafc","actorBorder":"#cbd5e1","actorTextColor":"#1e293b","signalColor":"#64748b","noteBkgColor":"#ecfdf5","noteBorderColor":"#5eead4"}}}%%
sequenceDiagram
    autonumber
    actor U as 用户
    participant F as FastAPI SSE
    participant T as Thought A1
    participant D as delegate_task
    participant C as A2A Client
    participant R as 远程 A2
    participant L as LLM

    U->>F: 跨 Agent 任务
    F->>T: route=thought
    T->>L: 推理
    T->>D: list_agents / delegate_task
    Note over F,U: tool_call SSE（A1 工具块）
    D->>C: 流式 SendMessage
    loop 远程过程
        C->>R: A2A
        R-->>C: trace / status
        C-->>D: on_event
        D-->>T: RemoteProcessEvent
        T-->>F: remote_delta
        Note over F,U: 嵌套「远程过程」面板
    end
    C-->>D: 最终 answer
    D-->>T: tool_result（短文本）
    T->>L: 汇总
    T-->>F: text_delta / turn_complete
    F-->>U: 最终回答
```

入站（外部 → Hubloom）摘要：外部拉 Card → SendMessage → bridge（`a2a_inbound=True`）→ CortexAgent → Artifact `answer` + `trace`。详解见 [A2A 互联](./Hubloom-A2A互联.md)。

### 说明

- **Chat 快答**：不经过 MCP / A2A，直接 LLM 回复。
- **Thought + MCP**：经 Gateway → Worker → 企业 API。
- **Thought + A2A**：`list_agents` / `delegate_task` → 远程 Agent；过程走 `remote_delta`，结果短文本进 LLM。
- **防环**：入站 A2A 回合禁止再 `delegate_task`（暂不支持入站后再派 A3）。
- SSE 事件：`thought_delta` · `tool_call` · `tool_result` · `remote_delta` · `text_delta` · `turn_complete`

---

## 模块详解

- [ADP 编排层](./Hubloom-ADP编排.md) — 路由决策、Chat / Thought 双路径
- [MCP 适配层](./Hubloom-MCP适配.md) — Swagger → 工具、网关与 Worker、Token 透传
- [A2A 互联](./Hubloom-A2A互联.md) — 双向 A2A：入站 Server + 出站 Client / 双通道 UI / 防环
- [工具层](./Hubloom-工具层.md) — BaseTool / Registry / Runner 与内置工具（含 A2A meta-tools）
- [记忆系统](./Hubloom-记忆系统.md) — 会话 / 长期记忆 / 离线提炼
- [RAG 知识库](./Hubloom-RAG知识库.md) — 文档入库 / 向量检索 / search_documents

---

## 导出高清图

预览仍不满意时，可复制代码到 [Mermaid Live Editor](https://mermaid.live) 导出 SVG/PNG。
