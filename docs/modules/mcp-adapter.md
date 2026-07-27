# MCP Adapter

> 状态：大纲（待编写正文）

## 本章要讲清

- 包内职责拆分：`discovery` / `spec` / `gateway` / `server` / `client` / `auth`
- 与 Agent 元工具、`HubloomRuntime` 的装配关系
- 子进程 worker 与 stdio 客户端生命周期
- （后续可再拆子页）各子目录的设计与调用链

## 代码锚点

- `src/mcp_adapter/discovery.py`
- `src/mcp_adapter/spec/`
- `src/mcp_adapter/gateway/`
- `src/mcp_adapter/server/`
- `src/mcp_adapter/client/`
- `src/mcp_adapter/auth.py`

## 相关章节

- 概念（先读）：[MCP 协议](../core-concepts/mcp-protocol.md)
- 上一篇：[Tools](tools.md)
- 下一篇：[Skill](skill.md)
- 使用：[接入 Swagger](../usage/import-swagger.md)
