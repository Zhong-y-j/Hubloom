# Tools

> 状态：大纲（待编写正文）

## 本章要讲清

- `BaseTool`、注册与 `ToolRunner`
- 内置工具面：`list_api` / `call_api`、`read_skill`、记忆 / RAG / A2A（按配置挂载）
- Agent 可见的 tools 列表如何组装（与 Runtime / MCP 的关系）

## 代码锚点

- `src/tools/base.py`、`runner.py`、`registry.py`
- `src/tools/builtin/`（`api_tools`、`skill_tools`、`memory_tool`、`retrieval_tool`、`a2a_tool`）

## 相关章节

- 上一篇：[Agent](agent.md)
- 下一篇：[MCP Adapter](mcp-adapter.md)
- 概念：[MCP](../core-concepts/mcp-protocol.md)
