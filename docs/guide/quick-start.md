# 5 分钟快速上手

> 状态：大纲（待编写正文）

## 本章要讲清

- 前置：Python 3.12+、复制 `config/env.example.yaml` → `env.yaml`
- 必填最小配置：`llm.*`、`mcp.swagger_url`（若启用 MCP）
- 启动后端（`main.py` / `:8010`）与示例前端（若需要）
- 用网页发一句能触发工具的问题，看到 Markdown 或表单
- 失败时看哪（`logs/debug.log`、健康检查）

## 读者学完应能

- 本机跑通一条「对话 → 调 API」演示链路

## 相关章节

- 装不明白：[安装与部署](installation.md)
- 配模型细讲：[配置 LLM](../usage/configure-llm.md)
- 接 Swagger 细讲：[接入 Swagger](../usage/import-swagger.md)
