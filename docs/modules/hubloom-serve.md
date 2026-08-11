# Hubloom Serve

**Hubloom Serve**（`src/server/`）是产品 HTTP 门面：对外提供对话、续跑、历史等接口；进程内持有一个 **Runtime**，把请求交给编排，再把事件编成 SSE 或 JSON 返回。

一句话：

> **收 HTTP → 调 Runtime → 用 `sse.py` 编码 → 同一次响应流回（或 JSON 一次返回）。**

演示前端在 `examples/chat/web/`，只负责 UI，通过代理打到本服务。

---

## 边界

**管：**

- 路由与请求/响应模型（`schemas.py`）
- Header 里的 `session_id` / 业务 Token
- session 锁、SSE 编码（`sse.py`）
- 生命周期里装配 Runtime；按配置挂上 Events / 企微

**不管：**

- 编排怎么决策 → [Agent](agent.md)
- OpenAPI 怎么变成工具、怎么打企业 HTTP → [MCP Adapter](mcp-adapter.md)
- Skill 怎么写、怎么加载 → [Skill](skill.md)
- Events / 企微业务怎么开、怎么联调 → [Events](events.md) · [企业微信](im-wecom.md) · [进阶](../advanced/README.md)

---

## 目录与关键入口

```text
src/server/
  app.py        # FastAPI 路由、_stream_chat / _stream_resume
  sse.py        # Agent 事件 → SSE 文本
  schemas.py    # ChatRequest / ResumeRequest / History 等
  assembly.py   # Events Dispatcher、企微 Adapter 装配
  cli.py        # python -m server serve
  __main__.py
main.py         # 仓库根入口（默认转成 serve）
```

启动后进程内单例：`_runtime`；若开启对应开关，还有 `_dispatcher`、`_wecom`。

---

## 主调用链：`POST /v1/chat`

流式（默认 `stream: true`）时大致是：

```text
客户端 POST /v1/chat
  → app.chat
  → StreamingResponse(_stream_chat(...))
       → session_lock.hold(session_id)
       → yield run_started
       → runtime.run_stream(...)          # Agent 边跑边 yield 事件
            → event_to_sse(item)          # sse.py 编码
            → yield SSE 行
       → yield run_finished
  ← 同一 HTTP 响应（text/event-stream）回到客户端
```

要点：

- 事件是 **Agent → Runtime → Serve 向上交回**，不是 Serve 旁路另开推送通道
- `sse.py` 只负责编码；真正写出响应的是 `app._stream_chat`
- `stream: false` 时走 `_run_chat_once`，一次返回 JSON（`ChatSyncResponse`）

**Resume：** 收到 `awaiting_user` 后，前端应带 `run_id` / `await_token` 调 `POST /v1/chat/resume`，不要再开一轮并行的 `/v1/chat`（同 session 有锁，也易触发「禁止并行 begin_run」）。

**History：** `GET /v1/chat/history` 读会话；可选 `include_thought=true`。若 session 正挂起，响应可带 `awaiting`，前端加载历史后应据此走 resume。

---

## 接口一览

主路径（常用）：

- `GET /health` — 探活（含 `events_enabled` / `wecom_enabled`）
- `POST /v1/chat` — 新一轮对话（SSE 或 JSON）
- `POST /v1/chat/resume` — interactive 挂起后续跑
- `GET /v1/chat/history` — 会话历史
- `GET /v1/mcp/status` — MCP 是否就绪

可选（需配置开启）：

- `GET /v1/events/types` · `POST /v1/events` — 业务事件入站
- `GET|POST /v1/im/wecom/callback` — 企微回调

交互式 OpenAPI：启动后打开 `http://127.0.0.1:<port>/docs`。

### 对话请求（节选）

```json
{
  "message": "帮我查一下状态",
  "session_id": "demo-1",
  "stream": true,
  "wait_profile": "interactive"
}
```

常用头：

- `X-Session-Id` — 也可放在 body 的 `session_id`
- `Authorization: Bearer …` 或 `X-MCP-Token` — 业务 Token，有则透传给 MCP；**不要写进 env.yaml**

SSE 事件名（节选）：`run_started` / `text_delta` / `thought_delta` / `step` / `tool_call` / `tool_result` / `awaiting_user` / `final_answer` / `run_complete` / `run_result` / `run_finished` / `error`。

### 续跑（节选）

```json
{
  "session_id": "demo-1",
  "user_reply": "小花",
  "run_id": "<await_run_id>",
  "await_token": "<await_token>",
  "stream": true
}
```

字段与事件全表可后补到 [API 参考](../reference/api-reference.md)；排错时也可对照 `schemas.py`、`sse.py`。

---

## 启动与依赖

```bash
# 仓库根；需已配置 config/env.yaml
PYTHONPATH=src uv run python main.py
# 或：PYTHONPATH=src uv run python -m server serve --config config/env.yaml

# 可选：演示前端
cd examples/chat/web && npm install && npm run dev
```

- 端口：`http.port`（常见 **8765**）
- **Redis 必填**（`redis.url`）：挂起态、session 锁；Events 幂等/串行、企微队列也共用
- LLM / MCP 等仍由 Runtime 按同一份 `env.yaml` 装配

---

## Serve 如何挂可选入口

**Events**（`events.enable=true`）：`assembly.build_event_dispatcher` 挂上 Dispatcher；Agent 侧 `wait_profile=no_wait`。路由在 `app.py` 的 `/v1/events*`。细则见 [Events](events.md)。

**企微**（`im.wecom.enable=true`）：`assembly.build_wecom_adapter` 挂上回调适配；回调尽快 ACK，消息进 Redis 会话队列异步跑 Agent。细则见 [企业微信](im-wecom.md)。

两者都是 **同一套 Runtime**，换的是入口，不是另起编排。

---

## 和上下游的关系

- **上游：** 演示前端 / 企业 BFF / 企微 / 业务 Webhook
- **下游：** `HubloomRuntime.run_stream` / `resume_stream`
- **并列模块：** 编排看 Agent；工具看 Tools + MCP；规程看 Skill

---

## 测试

- `tests/test_hubloom_serve.py` — chat / resume SSE 冒烟（ScriptedLLM，无真模型）
- `tests/test_hubloom_serve_events_wecom.py` — Events 幂等 + 企微回调 ACK
- `tests/test_hubloom_serve_chat_task.py` — 对**已启动**的 Serve 打真对话（需 LLM）

```bash
# 终端 1
PYTHONPATH=src uv run python main.py

# 终端 2
export HUBLOOM_SERVE_URL=http://127.0.0.1:8765
export HUBLOOM_MCP_TOKEN=你的业务Bearer   # mcp.enable 时需要
PYTHONPATH=src uv run python tests/test_hubloom_serve_chat_task.py
```

更多清单见 [测试计划](../community/testing.md)。

---

## 延伸阅读

- 概念：[架构](../core-concepts/architecture.md) · [Runtime](../core-concepts/runtime.md)
- 下一篇建议：[Runtime](runtime.md)
- 上手：[5 分钟快速上手](../guide/quick-start.md)
- 示例前端：[示例站](examples-chat.md)
