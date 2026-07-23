# Hubloom 回合交互契约

本轮「办事」与人机表单的绑定规则。实现：`src/agent/turn_state.py`；示例站 `/v1/chat` 已接入。

## 标识

| 字段 | 含义 |
|------|------|
| `session_id` / `threadId` | 整段会话 |
| `run_id` | **一轮** Agent 办事（用户一条自然语言触发，或后续 action 续跑） |

出站：`RUN_STARTED` / `RUN_FINISHED` 携带 `runId`（见 `agui_sse`）。  
人机等待中：进程内 `TurnStateStore` 按 session 保存至多一个 `waiting`。  
等待时额外推送 `CUSTOM name=hubloom.interaction_waiting`（`value.run_id`）。

## 入站：`POST /v1/chat`

**二选一：**

| 字段 | 说明 |
|------|------|
| `message` | 用户自然语言 |
| `action` + `run_id` | 表单 submit/cancel；`run_id` 必须等于当前 waiting |

`action` 形状：

```json
{
  "type": "submit",
  "name": "confirm_add_community",
  "payload": { "name": "阳光花园" },
  "surface_id": optional,
  "source_component_id": optional
}
```

服务端在锁内 `resolve_action` 后开**新** `run_id` 续跑 Agent；触发正文为结构化文案（含 `[A2UI:name]`，标明非闲聊），**不再**把表单伪造成普通用户气泡文本由前端拼接发送（有 `waitingRunId` 时）。

## 两种完成「添加」等任务的路径

1. **表单路径**：Respond 出 A2UI → `waiting(run_id=R)` → 用户 **submit/cancel** 带同一 `run_id=R` → 校验通过后清除 waiting → 新 run 续办。  
2. **对话路径**：用户不点表单，继续发自然语言 → **允许**。`supersede_if_waiting` → `CUSTOM hubloom.interaction_superseded` → 新 `run_id`；前端应关闭旧面板。

**不是**「等待中拒绝一切新消息」，也**不是**静默双轨（旧表单与新对话同时有效）。

## 校验（防串轮）

- `validate_action(session, run_id)`：无 waiting、或 `run_id` 不一致 → 错误（旧表单作废）。  
- 新 user message：先 `supersede_if_waiting`，再 `begin_run`。

## 状态

```text
空闲 --user message--> 跑 Agent(run_id)
                         | 出 A2UI
                         v
                    waiting(run_id)
                    /              \
            action submit/cancel   user message（对话补全）
                    \              /
                   清除 waiting；后者另开新 run
                         |
                    action 再开续跑 run
```

## 后续

- 对齐 AG-UI：`action` 译为 `role: tool` + `toolCallId` 再进 Runtime。  
- 文档中旧 `event: text_delta` 表以 `agui_sse` 为准；前端已按 `data.type` 解析。
