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
- Agent 当前仍以 Markdown / 工具事件流式输出；A2UI JSON 输出形态后续再设计
- 场景实验室用于摸 Catalog 与样式，与对话链路独立
