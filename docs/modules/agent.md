# Agent

> 状态：大纲（待编写正文）

## 本章要讲清

- 回合编排：`run_stream`、Think / Execute / Present / Respond
- `loop/` 各阶段职责与交班
- SSE / AG-UI 事件如何从编排层送出
- `turn_state`、prompts 与工具结果如何回流

## 代码锚点

- `src/agent/run.py`
- `src/agent/loop/`（`think` / `execute` / `present` / `respond` 等）
- `src/agent/agui_sse.py`、`sse.py`、`events.py`
- `src/agent/prompts.py`、`assemble.py`、`turn_state.py`

## 相关章节

- 上一篇：[Runtime](runtime.md)
- 下一篇：[Tools](tools.md)
- 概念：[AG-UI](../core-concepts/ag-ui-protocol.md) · [A2UI](../core-concepts/a2ui-protocol.md)
