# Hubloom `/v1/chat` SSE 契约

出站事件对齐 **AG-UI**（官方 `ag-ui-protocol`）：每帧为

```text
data: {"type":"<AGUI_TYPE>", ...}\n\n
```

实现：[`src/agent/agui_sse.py`](../src/agent/agui_sse.py)（`agent.sse` 为再导出）。  
人机回合 / `run_id` / 表单 action 见 [回合交互契约](./Hubloom-回合交互契约.md)。

示例站前端按 `data.type` 解析（兼容过渡期旧 `event:` 名）。

---

## 请求

- `POST /v1/chat`
- Headers：`X-Session-Id`；可选 `X-MCP-Token` / `Authorization`
- Body（二选一）：
  - `{ "message": string, "stream": true, "present_mode"?, "session_id"? }`
  - `{ "action": { "type": "submit"|"cancel", "name", "payload"?, "tool_call_id"? }, "run_id": string, "stream": true, ... }`

---

## 一轮典型顺序

```text
RUN_STARTED
  ├─（可选）THINKING_TEXT_MESSAGE_START → CONTENT* → END
  ├─ TOOL_CALL_START → ARGS* → END → TOOL_CALL_RESULT   # MCP 等服务端工具
  ├─ TEXT_MESSAGE_START → CONTENT* → END                # 助手 Markdown
  ├─ CUSTOM hubloom.a2ui / hubloom.a2ui_text            # A2UI 面板 / 侧栏文案
  ├─（若等人机）TOOL_CALL_* hubloom.a2ui_action         # 客户端表单工具
  ├─（若等人机）CUSTOM hubloom.interaction_waiting
RUN_FINISHED

# 用户提交表单后续跑：
TOOL_CALL_RESULT (同一 toolCallId) → RUN_STARTED → …
```

覆盖旧表单时，新消息流开头可出现 `CUSTOM hubloom.interaction_superseded`。

---

## 事件表（`type`）

| type | 说明 |
|------|------|
| `RUN_STARTED` | `threadId`=session，`runId`=本轮 |
| `RUN_FINISHED` | `result`: `route`, `final_message`, `answer_parts?`, `run_id` |
| `RUN_ERROR` | `message`；`code=recoverable` 时前端勿整条标红 |
| `TEXT_MESSAGE_START` | `messageId`, `role=assistant`；`rawEvent.source` 可选 |
| `TEXT_MESSAGE_CONTENT` | 同 `messageId` + `delta` |
| `TEXT_MESSAGE_END` | 同 `messageId` |
| `THINKING_TEXT_MESSAGE_START` / `CONTENT` / `END` | 内部思考流 |
| `TOOL_CALL_START` / `ARGS` / `END` | 工具调用；`ARGS.delta` 为 JSON 片段 |
| `TOOL_CALL_RESULT` | 工具返回；`rawEvent.toolCallName` / `isError` |
| `CUSTOM` | 见下表 `name` |

### `CUSTOM.name`

| name | value | 说明 |
|------|-------|------|
| `hubloom.phase` | `phase`, `route` | `thinking` / `presenting` / `replying` |
| `hubloom.a2ui` | `messages`, 可选 `replace` | A2UI 消息批次 |
| `hubloom.a2ui_text` | `delta` | A2UI 链路侧栏文案增量 |
| `hubloom.remote_delta` | `call_id`, `agent_id`, `channel`, `delta`, `status` | A2A 远程过程 |
| `hubloom.interaction_waiting` | `run_id`, `tool_call_id`, `kind` | 等待表单 |
| `hubloom.interaction_superseded` | `old_run_id`, `new_run_id`, `reason` | 新消息覆盖旧表单 |

客户端人机工具名：`hubloom.a2ui_action`（与 MCP 工具区分；前端不上屏为普通「调用」块）。

---

## 编码约定

- 编码器用官方 `EventEncoder`；Hubloom 附属字段 `session_id` / `run_id` 在编码前剥离，不进入 AG-UI 模型校验。
- 同一助手文本消息：`messageId` 在 START/CONTENT/END 间保持不变；工具调用前会先 `TEXT_MESSAGE_END`。
- 旧 `event: text_delta` / `turn_complete` 等仅作前端过渡兼容，新实现勿再依赖。
