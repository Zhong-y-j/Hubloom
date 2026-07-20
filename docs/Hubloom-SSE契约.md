# Hubloom `/v1/chat` SSE 契约（冻结草案）

重构期间**尽量保持事件名与字段兼容** [`examples/chat`](../examples/chat/)，避免前端同步大改。  
实现见 [`src/agents/sse.py`](../src/agents/sse.py)。

对照备份：以你本地备份 / git 历史中的旧实现为准校验行为；现仓库 `dev` 为重构工作树。

---

## 请求

- `POST /v1/chat`
- Headers：`X-Session-Id`、`X-MCP-Token` 或 `Authorization`（业务 Token）
- Body：`{ "message": string, "stream": true | false }`

## SSE 事件

| event | 主要 payload | 说明 |
|-------|----------------|------|
| `phase` | `phase`, `route` | `phase`: `thinking` / `replying`；重构后 `route` 固定为 `agent`（兼容期仍可能出现 `thought`） |
| `thought_delta` | `phase`, `delta` | 执行过程文本（内部笔记） |
| `tool_call` | `call_id`, `tool_name`, `args` | 工具调用 |
| `tool_result` | `call_id`, `tool_name`, `result`, `is_error` | 工具结果（result 可能截断） |
| `remote_delta` | `call_id`, `agent_id`, `channel`, `delta`, `status` | A2A 远程过程（可选） |
| `text_delta` | `delta` | 最终回复增量（Markdown） |
| `a2ui` | `messages`, 可选 `replace` | A2UI 消息批次 |
| `error` | `error`, 可选 `recoverable` | 错误 |
| `turn_complete` | `route`, `final_message`, `session_id`, `reason` | 一轮结束 |

## 兼容约定

- 示例站解析逻辑以 `event:` + `data:` JSON 为准。
- 重构后单一 ToolAgent：`route` 对外优先 `agent`；若旧前端写死 `thought`，服务端可双写或暂保留 `thought` 直至示例站更新。
- `FinalAnswerEvent` / `TextDeltaEvent` 均映射为 `text_delta`。
