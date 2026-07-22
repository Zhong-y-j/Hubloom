# Hubloom 工具层

工具层是 LLM 与外部能力之间的**统一接口**：所有能力（企业 API、文档检索、长期记忆、跨 Agent 委托）都被抽象成 `BaseTool`，注册进 `ToolRegistry`，由 `ToolRunner` 统一执行。LLM 不直接碰 HTTP 或数据库，只认注册表里的工具定义。

← 返回 [总体架构图](./Hubloom总体架构图.md) · [ADP 编排层](./Hubloom-ADP编排.md) · [MCP 适配层](./Hubloom-MCP适配.md) · [A2A 互联](./Hubloom-A2A互联.md)

---

## 模块组成

| 组件                    | 文件                              | 职责                                                          |
| ----------------------- | --------------------------------- | ------------------------------------------------------------- |
| **BaseTool**            | `tools/base.py`                   | 抽象基类：`name` / `description` / `parameters` / `execute()` |
| **ToolRegistry**        | `tools/registry.py`               | 注册表：name → tool；生成给 LLM 的 tools 定义                 |
| **ToolRunner**          | `tools/runner.py`                 | 执行器：白名单校验、重试、错误兜底                            |
| **APITools**            | `tools/builtin/api_tools.py`      | 原生 `list_api` / `call_api`，转发全量 MCP |
| **SearchDocumentsTool** | `tools/builtin/retrieval_tool.py` | RAG 文档检索（可选 hyde / mqe 查询优化）                      |
| **SearchMemoryTool**    | `tools/builtin/memory_tool.py`    | 长期记忆检索（情景 + 语义 + 可选联想图）                      |
| **ListAgentsTool**      | `tools/builtin/a2a_tool.py`       | 出站 A2A：列出 `A2A_REMOTE_AGENTS` 静态目录                   |
| **DelegateTaskTool**    | `tools/builtin/a2a_tool.py`       | 出站 A2A：委托远程 Agent；入站回合防环拒绝；过程旁路上屏      |

---

## 1. 组件关系

`ToolRegistry` 居中：启动时注册各类工具，运行时向 LLM 提供定义、向 Runner 提供实例。

```mermaid
%%{init: {"theme":"base","themeVariables":{"background":"#ffffff","primaryColor":"#ffffff","primaryBorderColor":"#cbd5e1","primaryTextColor":"#1e293b","lineColor":"#94a3b8","fontSize":"13px"}}}%%
flowchart TB
    REG["ToolRegistry<br/>name → BaseTool"]

    MCP1["list_api"] --> REG
    MCP2["call_api"] --> REG
    DOC["SearchDocumentsTool"] --> REG
    MEM["SearchMemoryTool"] --> REG
    A2A1["ListAgentsTool"] --> REG
    A2A2["DelegateTaskTool"] --> REG

    REG -->|"list_definitions()<br/>name + description + JSON Schema"| LLM["LLM<br/>tools 参数"]
    REG -->|"get(name)"| RUN["ToolRunner<br/>白名单 · 重试 ×2"]

    MCP1 -.->|"stdio"| GW["MCP Gateway<br/>→ Worker → 企业 API"]
    MCP2 -.->|"stdio"| GW
    DOC -.-> KB["KnowledgeBase<br/>ChromaDB"]
    MEM -.-> MM["MemoryManager<br/>Qdrant / Neo4j"]
    A2A1 -.-> DIR["A2A_REMOTE_AGENTS"]
    A2A2 -.-> CLIENT["a2a_adapter/client"]

    classDef reg fill:#f0fdfa,stroke:#2dd4bf,color:#0f766e
    classDef tool fill:#eff6ff,stroke:#60a5fa,color:#1e40af
    classDef backend fill:#f8fafc,stroke:#cbd5e1,color:#475569

    class REG,RUN reg
    class MCP1,MCP2,DOC,MEM,A2A1,A2A2 tool
    class LLM,GW,KB,MM,DIR,CLIENT backend
```

### 工具从哪里来？

| 工具                       | 注册时机                                                   | 位置                         |
| -------------------------- | ---------------------------------------------------------- | ---------------------------- |
| `list_api` / `call_api` | `HubloomAgent.create` → `build_api_tools`（原生 Tool，转发全量 MCP） | `tools/builtin/api_tools.py` · `hubloom/runtime.py` |
| `search_memory`            | `CortexAgent.attach_readonly_tools()`，需开启长期记忆      | `agents/adp/cortex_agent.py` |
| `search_documents`         | 同上，需配置 RAG 知识库                                    | 同上                         |
| `list_agents` / `delegate_task` | 同上，始终注册（出站 A2A）                            | 同上；详解见 [A2A 互联](./Hubloom-A2A互联.md) |

Agent 侧看到的业务 API 相关工具**只有 2 个元工具**（`list_api` / `call_api`），不是全量业务接口——见 [MCP 适配层](./Hubloom-MCP适配.md)。出站 A2A 另有 2 个工具，与之并列。

---

## 2. 一次工具调用链

Thought 执行阶段：LLM 产出 `tool_call` → Runner 分发 → 具体工具执行 → 观察结果回流。

```mermaid
%%{init: {"theme":"base","themeVariables":{"background":"#ffffff","actorBkg":"#f8fafc","actorBorder":"#cbd5e1","actorTextColor":"#1e293b","signalColor":"#64748b","noteBkgColor":"#f0fdfa","noteBorderColor":"#99f6e4"}}}%%
sequenceDiagram
    autonumber
    participant T as Thought.execute
    participant L as LLM
    participant R as ToolRunner
    participant B as BaseTool 实现
    participant X as MCP / RAG / Memory

    T->>L: generate_stream(messages, tools=定义列表)
    L-->>T: tool_calls [{name, arguments}]
    T-->>T: yield ToolCallEvent（SSE: tool_call）

    T->>R: run(name, args)
    R->>R: 白名单校验 · registry.get(name)

    loop 最多 2 次
        R->>B: execute(**args)
        B->>X: 实际调用（stdio / 向量检索）
        X-->>B: 结果
        B-->>R: 文本 / JSON 字符串
    end

    R-->>T: (result, is_error)
    T-->>T: yield ToolResultEvent（SSE: tool_result）
    Note over T: 结果追加进 _observations<br/>与 execute messages

    T->>L: 携带工具结果继续推理
```

### ToolRunner 的兜底策略

- **白名单**：`allowed_tools` 之外的调用直接拒绝（当前默认不限制）。
- **重试**：`execute()` 抛异常时最多重试 2 次，间隔递增（0.3s × attempt）。
- **不抛出**：所有失败都转成 `(错误文本, is_error=True)` 返回，由 Thought 决定是否 replan，不会中断整轮对话。

---

## 3. 工具定义如何进入 LLM

同一份注册表，喂给 LLM 两种形态：

```mermaid
%%{init: {"theme":"base","themeVariables":{"background":"#ffffff","primaryColor":"#ffffff","primaryBorderColor":"#cbd5e1","primaryTextColor":"#1e293b","lineColor":"#64748b","fontSize":"14px"}}}%%
flowchart LR
    REG["ToolRegistry"]

    REG -->|"list_definitions()"| DEF["tools 参数<br/>function calling 用<br/>（仅 Thought.execute）"]
    REG -->|"format_tool_summaries()"| SUM["工具简表文本<br/>注入 system prompt<br/>（Chat / deliberate 均可见）"]

    DEF --> P1["LLM 可发起 tool_call"]
    SUM --> P2["LLM 知道有哪些能力<br/>但不能直接调用"]

    classDef reg fill:#f0fdfa,stroke:#2dd4bf,color:#0f766e
    classDef form fill:#eff6ff,stroke:#60a5fa,color:#1e40af
    classDef out fill:#f8fafc,stroke:#cbd5e1,color:#475569

    class REG reg
    class DEF,SUM form
    class P1,P2 out
```

- **Thought.execute** 是唯一真正传 `tools` 参数、允许 function calling 的阶段。
- **Chat / deliberate / respond** 只在 system prompt 里看到工具简表和「API 分组」目录，用于介绍能力、规划步骤，但 `tools=None`，不会产生调用。

---

## 关键代码路径

```
tools/
├── base.py               # BaseTool 抽象：name / description / parameters / execute()
├── registry.py           # ToolRegistry：register / get / list_definitions
├── runner.py             # ToolRunner：白名单 + 重试 + 错误兜底
└── builtin/
    ├── api_tools.py     # list_api / call_api（主路径）
    ├── retrieval_tool.py # SearchDocumentsTool：RAG 检索 + hyde/mqe 优化
    ├── memory_tool.py    # SearchMemoryTool：情景/语义/联想图检索
    └── a2a_tool.py       # list_agents / delegate_task（出站 A2A + 防环）

hubloom/runtime.py        # create 时：catalog + 全量 MCP + build_api_tools
agents/adp/thought.py     # execute() 消费 tool_defs；delegate_task 时旁路 RemoteProcessEvent
agents/adp/cortex_agent.py # attach_readonly_tools 注册 memory/RAG/A2A
a2a_adapter/client/       # registry / transport / mapping
```

---

## 相关文档

- [ADP 编排层](./Hubloom-ADP编排.md) — Thought.execute 的 ReAct 循环
- [MCP 适配层](./Hubloom-MCP适配.md) — 全量 worker + 原生元工具
- [A2A 互联](./Hubloom-A2A互联.md) — 出站委托、双通道 UI、入站防环
- [记忆系统](./Hubloom-记忆系统.md) — SearchMemoryTool 背后的 MemoryManager
- [RAG 知识库](./Hubloom-RAG知识库.md) — SearchDocumentsTool 背后的 KnowledgeBase
