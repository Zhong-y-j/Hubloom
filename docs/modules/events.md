# Events

> 状态：大纲（待编写正文）

## 本章要讲清

- `POST /v1/events` 入站 → dispatcher → 注入分册 → 跑 Agent
- 类型发现、幂等（`event_id`）、与 `skills/events/` 的关系

## 代码锚点

- `src/events/`（`dispatcher.py`、`catalog.py`、`idempotency.py`、`models.py`）

## 相关章节

- 进阶：[事件 Webhook](../advanced/webhook.md)
- Skill 分册：[Skill 模块](skill.md)
