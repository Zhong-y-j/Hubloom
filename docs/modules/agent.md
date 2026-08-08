# Agent

> 状态：大纲（待编写正文）。  
> **最终架构**：[Policy-Bounded Typed ReAct](agent-architecture.md) · **过程备忘**：[重构设计备忘](agent-design.md)

## 本章要讲清

- 回合编排：`run_stream`（**现状**仍为 Think / Execute / Present / Respond；目标见架构文）
- `loop/` 各阶段职责与交班
- SSE / AG-UI 事件如何从编排层送出
- `turn_state`、prompts 与工具结果如何回流

## 代码锚点

- `src/agent/run.py`
- `src/agent/loop/`（`think` / `execute` / `present` / `respond` 等）
- `src/agent/agui_sse.py`、`sse.py`、`events.py`
- `src/agent/prompts.py`、`assemble.py`、`turn_state.py`

## 相关章节

- 最终架构：[agent-architecture.md](agent-architecture.md)
- 过程备忘：[agent-design.md](agent-design.md)
- 上一篇：[Runtime](runtime.md)
- 下一篇：[Tools](tools.md)
- 概念：[架构](../core-concepts/architecture.md) · [MCP](../core-concepts/mcp-protocol.md)
