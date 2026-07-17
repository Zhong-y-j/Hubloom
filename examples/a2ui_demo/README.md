# A2UI Demo

Vue 前端 + HubloomAgent 后端。两个模式：

1. **Agent 对话** — 与 `examples/chat` 同源：`POST /v1/chat` SSE，凭证 Token + 用户 ID
2. **A2UI 场景实验室** — 本地 `scenarios.ts` 对照组件渲染（不经 Agent）

## 启动

需已配置 `config/env.yaml`（与主 chat 相同）。

```bash
# 终端 1 — 后端（默认 8010）
uv run python -m examples.a2ui_demo

# 终端 2 — 前端（代理 /v1 → 8010）
cd examples/a2ui_demo/web
npm install
npm run dev
```

打开 http://127.0.0.1:5173/ → 默认「Agent 对话」。

## 说明

- 前端只传业务 Token + 用户 ID；LLM / Swagger 由服务端 `env.yaml` 加载
- Thought 最终回复为 A2UI（`<a2ui-json>` 块）；List 场景可用 `$hubloom_tool` 哨兵，由运行时把本轮 `tool_result` 填进 `updateDataModel`
- Chat 快答仍为 Markdown，不产出 A2UI
- 按钮 action：前端拼成 `[A2UI:<name>]` 用户消息走 `/v1/chat`（删除建议两步确认）
- 场景实验室用于摸 Catalog 与样式，与对话链路独立
