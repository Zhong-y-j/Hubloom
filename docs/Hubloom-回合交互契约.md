# Hubloom 回合交互契约（P0）

本轮「办事」与人机表单的绑定规则。实现：`src/agent/turn_state.py`；示例站流式入口已接入。

## 标识

| 字段 | 含义 |
|------|------|
| `session_id` / `threadId` | 整段会话 |
| `run_id` | **一轮** Agent 办事（用户一条自然语言触发，或后续 action 续跑） |

出站：`RUN_STARTED` / `RUN_FINISHED` 携带 `runId`（见 `agui_sse`）。  
人机等待中：进程内 `TurnStateStore` 按 session 保存至多一个 `waiting`。

## 两种完成「添加」等任务的路径（分情况）

用户本轮需要「添加一条内容」时：

1. **表单路径**：Respond 出 A2UI → 进入 `waiting(run_id=R)` → 用户 **submit/cancel** 必须带同一 `run_id=R`（P1 入站实现校验）。  
2. **对话路径**：用户不点表单，继续发自然语言让 Agent 添加 → **允许**。服务端将旧 `waiting` 标为 `superseded_by_message` 并清除，再开新 `run_id`；出站可发 `CUSTOM name=hubloom.interaction_superseded`，前端应关闭旧面板。

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
```

## 后续（非 P0）

- P1：`/v1/chat` 结构化 `action` + `resolve_action`；前端提交带 `run_id`。  
- 对齐 AG-UI：`action` 译为 `role: tool` + `toolCallId`。  
- 文档中旧 `event: text_delta` 表以 `agui_sse` 为准逐步替换。
