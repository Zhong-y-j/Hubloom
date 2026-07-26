---
name: events
description: >
  业务事件驱动任务总册。当会话由 Webhook / POST /v1/events 触发，或用户提到
  事件处理、locker.created、locker.offline、order.refund 等事件类型时使用。
  具体步骤在 skills/events/ 下各分册 md；事件入站时 Runtime 会注入对应分册正文。
---

# Events（事件处理总则）

本 Skill 是**事件玩法总册**。支持的事件类型 = 本目录下除 `SKILL.md` 外、带 frontmatter `event:` 的 `*.md` 分册（API 亦据此发现）。

## 总则（所有事件共用）

1. **先按分册规程办事**，再交 Respond 总结；禁止未查证就编造业务结论。
2. **默认只读**：查列表 / 详情、分析、给建议。删除、禁用、改绑、退款执行等写操作，须用户或运维**明确确认**后才可 `call_api`。
3. 业务接口仍走 MCP（`list_api` / `call_api`）；工具名以 `list_api` 返回为准（注意大小写）。
4. 对话中若需回顾总则：`read_skill(skill=events)`。事件轮次里对应分册通常已注入触发消息，不必再为读分册空转。

## 分册索引

| 文件 | event | 处理取向 |
|------|-------|----------|
| `locker-created.md` | `locker.created` | 核对登记是否可见、小区绑定是否正确 |
| `locker-offline.md` | `locker.offline` | 诊断离线原因与建议，不擅自改设备 |
| `order-refund.md` | `order.refund` | 以总结与风险说明为主，默认不执行退款 |

新增事件：在本目录增加 `*.md`（frontmatter 必填 `event`），重启服务即可被 `POST /v1/events` 与 `GET /v1/events/types` 识别。
