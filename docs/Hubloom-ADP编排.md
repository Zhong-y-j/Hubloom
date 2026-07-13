# Hubloom ADP 编排层

ADP（Agent Decision Path）是 Hubloom 的**编排中枢**：接收用户消息，评估路由，分流到快答或深度思考，并负责上下文装配与落库。

← 返回 [总体架构图](./Hubloom总体架构图.md)

---

## 模块组成

| 组件 | 文件 | 职责 |
|------|------|------|
| **CortexAgent** | `agents/adp/cortex_agent.py` | 单轮编排入口：recall → 路由 → 执行 → 落库 |
| **Assessor** | `agents/adp/assessor.py` | 静默评估，输出 `need_deep_think` |
| **Chat** | `agents/adp/chat.py` | 快答路径：流式直答，不调用工具 |
| **Thought** | `agents/adp/thought.py` | 深思考路径：研判 → 执行 → 重规划 → 回复 |

---

## 1. 路由决策

Assessor 用 LLM 非流式输出 JSON，判断本轮走 Chat 还是 Thought。

```mermaid
%%{init: {"theme":"base","themeVariables":{"background":"#ffffff","primaryColor":"#ffffff","primaryBorderColor":"#cbd5e1","primaryTextColor":"#1e293b","lineColor":"#64748b","fontSize":"14px"}}}%%
flowchart TD
    START([用户消息]) --> RECALL[读取会话历史<br/>]
    RECALL --> ASSESS[Assessor 评估<br/>LLM → JSON]

    ASSESS --> Q{need_deep_think?}

    Q -->|false| CHAT_ROUTE[Route.CHAT<br/>快答]
    Q -->|true| THOUGHT_ROUTE[Route.THOUGHT<br/>深思考]

    CHAT_ROUTE --> ASM_C[装配 Chat 上下文<br/>ContextAssembler]
    THOUGHT_ROUTE --> ASM_T[装配 Thought 上下文<br/>+ 长期记忆 recall]

    ASM_C --> RUN_C[Chat.run_stream]
    ASM_T --> RUN_T[Thought.run_stream]

    RUN_C --> PERSIST[落库 ASSISTANT<br/>+ thought / tools 元数据]
    RUN_T --> PERSIST

  PERSIST --> END([SSE 结束])

    classDef entry fill:#eff6ff,stroke:#60a5fa,color:#1e40af
    classDef decision fill:#fef9c3,stroke:#facc15,color:#854d0e
    classDef chat fill:#ecfdf5,stroke:#34d399,color:#047857
    classDef thought fill:#f0fdfa,stroke:#2dd4bf,color:#0f766e
    classDef store fill:#f8fafc,stroke:#cbd5e1,color:#475569

    class START,END entry
    class Q decision
    class CHAT_ROUTE,ASM_C,RUN_C chat
    class THOUGHT_ROUTE,ASM_T,RUN_T thought
    class RECALL,PERSIST store
```

### Assessor 输出

```json
{
  "need_deep_think": true,
  "reason": "需要查询库存数据"
}
```

| 路由 | 典型场景 |
|------|----------|
| **Chat** | 寒暄、能力介绍、概念解释、无需调 API |
| **Thought** | 查数、创建/更新/删除、需多步工具调用 |

评估过程**不对用户展示**；路由结果通过 `PhaseEvent` 告知前端（`replying` / `thinking`）。

---

## 2. 单轮编排时序

CortexAgent 每轮对话的完整链路。

```mermaid
%%{init: {"theme":"base","themeVariables":{"background":"#ffffff","actorBkg":"#f8fafc","actorBorder":"#cbd5e1","actorTextColor":"#1e293b","signalColor":"#64748b","noteBkgColor":"#f0fdfa","noteBorderColor":"#99f6e4"}}}%%
sequenceDiagram
    autonumber
    actor U as 用户
    participant F as FastAPI
    participant CA as CortexAgent
    participant M as Memory
    participant AS as Assessor
    participant L as LLM
    participant P as Chat / Thought

    U->>F: POST /v1/chat
    F->>CA: run_stream(task)

    CA->>M: recall 会话历史
    CA->>AS: evaluate
    AS->>L: 路由判断（非流式 JSON）
    L-->>AS: need_deep_think
    AS-->>CA: AssessResult

    CA->>M: remember USER
    CA->>M: recall 长期记忆（可选）
    CA->>CA: ContextAssembler 装配 messages

    alt Route.CHAT
        CA->>P: Chat.run_stream
        P->>L: 流式直答（无 tools）
    else Route.THOUGHT
        CA->>P: Thought.run_stream
        Note over P: deliberate → execute → respond
    end

    P-->>CA: AgentEvent 流
    CA-->>F: SSE 转发
    F-->>U: 思考过程 + 最终回复

    CA->>M: remember ASSISTANT + metadata
```

---

## 3. Chat 快答路径

简单直接：装配上下文后，LLM 流式输出，**不注册 tools、不执行 tool_call**。

```mermaid
%%{init: {"theme":"base","themeVariables":{"background":"#ffffff","actorBkg":"#ecfdf5","actorBorder":"#34d399","actorTextColor":"#047857","signalColor":"#64748b"}}}%%
sequenceDiagram
    autonumber
    participant CA as CortexAgent
    participant ASM as ContextAssembler
    participant C as Chat
    participant L as LLM

  CA->>ASM: system + 历史 + 长期记忆 + 当前任务
    ASM-->>CA: messages
    CA->>C: run_stream(messages)
    C->>L: generate_stream（tools=None）

    loop 流式输出
        L-->>C: delta
        C-->>CA: FinalAnswerDeltaEvent
    end

    L-->>C: StreamEndEvent
    C-->>CA: FinalAnswerEvent
```

SSE 事件：`text_delta` → `turn_complete`

---

## 4. Thought 深思考循环

Thought 分四个阶段，思考过程与最终回复**分区展示**。

```mermaid
%%{init: {"theme":"base","themeVariables":{"background":"#ffffff","primaryColor":"#ffffff","primaryBorderColor":"#cbd5e1","primaryTextColor":"#1e293b","lineColor":"#64748b","fontSize":"13px"}}}%%
flowchart TD
    START([Thought.run_stream]) --> D1["① deliberate<br/>BEFORE_EXECUTE<br/>内部工作笔记"]

    D1 --> EX["② execute<br/>ReAct 工具循环"]
    EX --> TC{工具调用}
    TC -->|list_tools / call_tool| TOOL[ToolRunner → MCP / RAG / Memory]
    TOOL --> EX

    EX --> RP_Q{should_replan?<br/>失败或步数上限}
    RP_Q -->|是| D2["③ replan<br/>REPLAN<br/>调整策略"]
    D2 --> EX
    RP_Q -->|否| D3["④ deliberate<br/>AFTER_EXECUTE<br/>执行摘要"]

    D3 --> RSP["⑤ respond<br/>组织最终回复"]
    RSP --> END([FinalAnswerEvent])

    classDef deliberate fill:#f0fdfa,stroke:#2dd4bf,color:#0f766e
    classDef execute fill:#fff7ed,stroke:#fdba74,color:#9a3412
    classDef respond fill:#eff6ff,stroke:#60a5fa,color:#1e40af
    classDef decision fill:#fef9c3,stroke:#facc15,color:#854d0e

    class D1,D2,D3 deliberate
    class EX,TC,TOOL execute
    class RSP respond
    class RP_Q decision
```

### 阶段与 SSE 事件

| 阶段 | 方法 | 用户可见 | SSE 事件 |
|------|------|----------|----------|
| 执行前研判 | `deliberate(BEFORE_EXECUTE)` | 思考过程区 | `thought_delta` |
| 工具执行 | `execute()` | 思考过程区 | `tool_call` · `tool_result` |
| 重规划 | `replan()` → `deliberate(REPLAN)` | 思考过程区 | `thought_delta` |
| 执行后总结 | `deliberate(AFTER_EXECUTE)` | 思考过程区 | `thought_delta` |
| 最终回复 | `respond()` | **最终结果区** | `text_delta` · `turn_complete` |

### 重规划触发条件

`should_replan()` 在以下情况进入 replan 循环（最多 `max_replan_rounds` 次）：

- 工具调用失败（`_execute_had_errors`）
- 达到最大执行步数（`_execute_hit_step_limit`）
- **不触发**：鉴权失败（`_auth_failure_detected`）— 直接结束执行，由 respond 告知用户

---

## 5. 组件关系

```mermaid
%%{init: {"theme":"base","themeVariables":{"background":"#ffffff","primaryColor":"#ffffff","primaryBorderColor":"#cbd5e1","primaryTextColor":"#1e293b","lineColor":"#94a3b8","fontSize":"13px"}}}%%
flowchart TB
    CA["CortexAgent<br/>编排入口"]

    CA --> AS["Assessor<br/>路由评估"]
    CA --> CH["Chat<br/>快答"]
    CA --> TH["Thought<br/>深思考"]

    CA --> MM["MemoryManager<br/>会话 recall / remember"]
    CA --> ASM["ContextAssembler<br/>上下文裁剪与装配"]

    AS --> LLM["LLMProvider"]
    CH --> LLM
    TH --> LLM

    TH --> TR["ToolRegistry<br/>MCP · RAG · Memory 工具"]
    TR --> RUN["ToolRunner"]

    classDef hub fill:#f0fdfa,stroke:#2dd4bf,color:#0f766e
    classDef path fill:#eff6ff,stroke:#60a5fa,color:#1e40af
    classDef infra fill:#f8fafc,stroke:#cbd5e1,color:#475569

    class CA hub
    class AS,CH,TH path
    class MM,ASM,LLM,TR,RUN infra
```

---

## 关键代码路径

```
agents/adp/
├── cortex_agent.py   # run_stream() 单轮编排主入口
├── assessor.py       # Assessor.evaluate() 路由 JSON
├── chat.py           # Chat.run_stream() 快答
├── thought.py        # Thought.run_stream() 深思考四阶段
└── prompts.py        # ASSESSOR_SYSTEM / THOUGHT_CONTEXT_SYSTEM

agents/api/app.py     # HTTP → CortexAgent.run_stream → SSE
agents/events.py      # ThoughtDeltaEvent / ToolCallEvent / FinalAnswerEvent …
memory/context.py     # ContextAssembler 上下文装配
```

---

## 下一步

- [MCP 适配层](./Hubloom-MCP适配.md) — Thought 工具调用的底座
- [工具层](./Hubloom-工具层.md) — ToolRegistry / ToolRunner 与内置工具
