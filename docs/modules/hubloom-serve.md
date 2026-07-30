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

默认端口见配置 `http.port`（常见 8765）。须配置并启动 **Redis**（`redis.url`）：挂起态与按 session 锁均走 Redis，无进程内存回退。OpenAPI：`/docs`。

## 接口（无 A2UI / AG-UI）

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| GET | `/health` | 探活 |
| POST | `/v1/chat` | 新一轮对话（SSE 或 JSON）**走 Runtime + 真 LLM** |
| POST | `/v1/chat/resume` | interactive 挂起后续跑 |
| GET | `/v1/chat/history` | 会话历史 |
| GET | `/v1/mcp/status` | MCP 就绪 |

## 测试怎么分

| 文件 | 是否真 LLM | 用途 |
| --- | --- | --- |
| `tests/test_hubloom_serve.py` | 否（ScriptedLLM） | CI 冒烟：路由 / SSE 形状 |
| `tests/test_hubloom_serve_chat_task.py` | **是** | 联调：对**已启动**的 serve 打 `/v1/chat` |

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
