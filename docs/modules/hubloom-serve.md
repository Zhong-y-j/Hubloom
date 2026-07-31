# Hubloom Serve（产品 HTTP API）

> 演示前端：`examples/chat/web`（仅前端，代理到本服务；无 A2UI / AG-UI）。

## 启动

```bash
# 仓库根；需已配置 config/env.yaml（含真 LLM）
PYTHONPATH=src .venv/bin/python -m server serve --config config/env.yaml
# 或：PYTHONPATH=src .venv/bin/python main.py

# 可选：演示前端
cd examples/chat/web && npm install && npm run dev
```

默认端口见配置 `http.port`（常见 8765）。须配置并启动 **Redis**（`redis.url`）：挂起态、session 锁、Events 幂等/串行、企微会话队列均走 Redis。OpenAPI：`/docs`。

## 接口（无 A2UI / AG-UI）

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| GET | `/health` | 探活（含 `events_enabled` / `wecom_enabled`） |
| POST | `/v1/chat` | 新一轮对话（SSE 或 JSON） |
| POST | `/v1/chat/resume` | interactive 挂起后续跑 |
| GET | `/v1/chat/history` | 会话历史；`include_thought=true` 时填回 `thought` |
| GET | `/v1/mcp/status` | MCP 就绪 |
| GET | `/v1/events/types` | 已登记事件类型（需 `events.enable`） |
| POST | `/v1/events` | 业务 Webhook 入站（需 `events.enable`） |
| GET/POST | `/v1/im/wecom/callback` | 企微 URL 验证与消息回调（需 `im.wecom.enable`） |

## Events

- 配置：`events.enable` / `shared_secret`（头 `X-Event-Secret`）/ `result_callback_url` / `catalog`
- Redis：`event_id` 幂等 + `session_id` 串行；与 chat 共用 `redis.url`
- Agent：`wait_profile=no_wait`；Bearer 仅来自事件体 `bearer_token`
- 规程：`skills/events/*.md`

```bash
curl -sS -X POST "http://127.0.0.1:8765/v1/events" \
  -H "Content-Type: application/json" \
  -H "X-Event-Secret: change-me" \
  -d '{"event_id":"evt-1","type":"locker.created","session_id":"demo-1","payload":{"deviceId":"LK-A-001"}}'
```

## 企微 IM

- 配置：`im.wecom.enable` + corp 凭证 + 回调 `token` / `encoding_aes_key`
- 回调尽快空 200，消息入 Redis 会话队列异步跑 Agent
- **短回复**：默认 `max_reply_chars=650`；企微通道把纯文本短回复要求注入 **system**（不拼进用户消息）；推送使用应用消息 `msgtype=text`；完整内容仍写会话历史
- 会话键：`{session_prefix}:{UserId}`（默认 `wecom:…`）
- 换票：`im.wecom.token_resolve`（可选；未配则 Bearer 为空）

## 测试怎么分

| 文件 | 是否真 LLM | 用途 |
| --- | --- | --- |
| `tests/test_hubloom_serve.py` | 否（ScriptedLLM） | chat / resume SSE 冒烟 |
| `tests/test_hubloom_serve_events_wecom.py` | 否 | Events 幂等 + 企微回调 ACK 冒烟 |
| `tests/test_hubloom_serve_chat_task.py` | **是** | 联调：对**已启动**的 serve 打 `/v1/chat` |
| `tests/test_events.py` | 否（FakeAgent） | Events 调度层（需 Redis） |
| `tests/test_im_wecom.py` | 否 | 企微 send/echo/queue 联调 |

真模型联调：

```bash
# 终端 1
PYTHONPATH=src .venv/bin/python -m server serve --config config/env.yaml

# 终端 2
export HUBLOOM_SERVE_URL=http://127.0.0.1:8765
export HUBLOOM_MCP_TOKEN=你的业务Bearer   # mcp.enable 时需要
PYTHONPATH=src .venv/bin/python tests/test_hubloom_serve_chat_task.py
```

可选：`HUBLOOM_CHAT_MESSAGE` / `HUBLOOM_WAIT_PROFILE=interactive` / `HUBLOOM_RESUME_REPLY=小花`。

### POST /v1/chat

```json
{
  "message": "帮我加一只宠物",
  "session_id": "demo-1",
  "stream": true,
  "wait_profile": "interactive"
}
```

Header：`X-Session-Id`；业务 Token（`Authorization` / `X-MCP-Token`）**可选**，有则注入 MCP 鉴权。

SSE 事件（节选）：`run_started` / `step` / `tool_call` / `tool_result` / `awaiting_user` / `run_complete` / `run_result` / `run_finished`。

### POST /v1/chat/resume

收到 `awaiting_user` 后：

```json
{
  "session_id": "demo-1",
  "user_reply": "小花",
  "run_id": "<await_run_id>",
  "await_token": "<await_token>",
  "stream": true
}
```

### GET /v1/chat/history

查询参数：

- `session_id`（或头 `X-Session-Id`）
- `include_thought`（默认 `false`）：为 `true` 时在**最终助手消息**上填回 `thought`（含中间工具轮折叠进来的思考）

响应还可带 `awaiting`（`run_id` / `await_token` / `kind` / `prompt`）：session 正挂起等人时返回，前端加载历史后应据此走 `/v1/chat/resume`，避免误调 `/v1/chat` 触发「禁止并行 begin_run」。

面向聊天 UI：带 `tool_calls` 的中间 assistant / tool 行会折叠进最终助手气泡的 `tools`（及可选 `thought`），与实时 SSE 一条气泡一致。

```bash
curl -s "http://127.0.0.1:8765/v1/chat/history?session_id=demo-1&include_thought=true"
```

助手消息示例字段：`role` / `content` / `created_at` / `source` / `thought`（可选）。
