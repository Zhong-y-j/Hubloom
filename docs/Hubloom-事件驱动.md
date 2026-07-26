# Hubloom 事件驱动

业务系统主动推送事件 → Hubloom 注入对应 Skill 分册规程 → 跑一轮 Agent → 结果写入指定会话历史。  
实现：`src/events/`；示例站：`POST /v1/events`、`GET /v1/events/types`。

与对话路径的关系：**不走** `/v1/chat` 的 AG-UI 流式协议；共用 `HubloomRuntime.run_stream`（`trigger_source=event`），会话与工具鉴权模型一致。

---

## 定位

| 问题 | 说明 |
|------|------|
| 谁调谁 | **业务后端 → Hubloom**（Webhook），不是 Swagger 里的业务 API |
| Agent 何时动 | 事件到达后**主动**跑一轮，用户不必先开口 |
| 结果落哪 | 指定 `session_id` 的对话历史（刷新 Web 页可看；带「事件」标记） |
| 怎么办实事 | 仍经 MCP `list_api` / `call_api` 调企业 OpenAPI |
| 玩法写哪 | [`skills/events/`](../skills/events/) 分册；**入站时固定注入**，不依赖 Agent 再 `read_skill` |

后续可扩展：消息队列、定时轮询、IM 主动触达——本页只描述当前 Webhook MVP。

---

## 主链路

```text
业务系统
  │  POST /v1/events  (+ X-Event-Secret)
  ▼
normalize_event → EventCatalog（扫 skills/events/*.md）
  │  未知 type → 400；缺 payload 必填 → 400
  │  同 event_id → 幂等直接返回上次结果
  ▼
渲染触发文案（事件字段 + 分册规程正文）
  ▼
HubloomRuntime.run_stream(
  trigger_source="event",
  present_mode="markdown",
  bearer_token=事件或 default_bearer_token
)
  ▼
Think →（可选 Present）→ Respond
  │  写入 conversation（user.source=event）
  ▼
同步 JSON：ok / summary / duplicate …
  （可选 result_callback_url 回调业务）
```

---

## HTTP 契约（示例站）

### 配置

`config/env.yaml`：

```yaml
events:
  enable: true
  shared_secret: change-me
  # default_bearer_token: ...   # 事件未带 bearer_token 时回退
  # result_callback_url: https://biz.example/hooks/hubloom-event-result
  # catalog:                    # 可选：覆盖/追加类型
  #   locker.created:
  #     title: 钥匙柜已登记（覆盖）
```

- `enable: false` → `/v1/events*` 返回 503  
- 配置了 `shared_secret` 时，请求头 `X-Event-Secret` 必须一致；未配置则跳过校验（仅建议本地）

### `GET /v1/events/types`

列出当前支持的事件类型（扫描分册，无需在 API 代码里维护列表）。

```bash
curl -s http://127.0.0.1:8010/v1/events/types \
  -H "X-Event-Secret: change-me"
```

响应字段要点：`types[].type` / `title` / `description` / `payload_fields` / `playbook_file`。

### `POST /v1/events`

```json
{
  "event_id": "evt-locker-001",
  "type": "locker.created",
  "session_id": "demo-session",
  "occurred_at": "2026-07-26T14:00:00Z",
  "bearer_token": "业务 Token（可选）",
  "instruction": "覆盖分册的临时指令（可选，一般不用）",
  "payload": {
    "deviceId": "523026567",
    "cabinetName": "B01",
    "gatedCommunityName": "鄞新电力"
  }
}
```

| 字段 | 必填 | 说明 |
|------|------|------|
| `event_id` | 是 | **幂等键**（不是 `session_id`）；重复提交返回 `duplicate: true` 与上次结果 |
| `type` | 是 | 须在分册 / catalog 中存在 |
| `session_id` | 是 | 写入哪条会话历史；业务侧选定运维/值班会话 |
| `payload` | 否 | object；分册 `payload_fields` 列出的键若为空会 400 |
| `bearer_token` | 否 | 透传 MCP；否则用 `events.default_bearer_token` |
| `instruction` | 否 | 若提供则**整段替换**注入的分册正文（调试用） |
| `occurred_at` | 否 | 原样写入触发文案 |

成功响应（同步，等 Agent 跑完）：

```json
{
  "event_id": "…",
  "session_id": "…",
  "type": "locker.created",
  "ok": true,
  "duplicate": false,
  "summary": "Respond 终稿 Markdown",
  "error": null,
  "turn_count": 3
}
```

与 `/v1/chat` **共用进程内运行锁**：同一时刻只跑一轮 Agent（对话或事件）。

---

## Skill 分册（真相源）

合法结构（符合 `skills/<id>/SKILL.md` 扫描规范）：

```text
skills/events/
  SKILL.md                 # 总则；对话侧可 read_skill(events)
  locker-created.md        # frontmatter.event: locker.created
  locker-offline.md
  order-refund.md
```

**不要**写成 `skills/events/locker-created/SKILL.md`（嵌套目录不会被 `load_skills` 加载）。

分册 frontmatter 示例：

```yaml
---
event: locker.created          # 必填：事件 type
title: 钥匙柜已登记
description: 一句话说明
payload_fields:
  - deviceId
hint_tags:
  - VehicleKeySmartLocker
  - GatedCommunity
---
# 步骤 / 禁止项 / 完成标准 …
```

| 机制 | 行为 |
|------|------|
| 发现 | 启动时扫 `*.md`（跳过 `SKILL.md`）；`GET /v1/events/types` 同源 |
| 注入 | Dispatcher 把分册正文写入本轮 user 触发（`【事件处理规程 · …】`） |
| 覆盖 | `events.catalog.<type>` 可改 title / playbook / `payload_fields`，或追加纯 YAML 类型 |
| 二次开发 | 新增事件 = 加一个分册 md + 重启；一般不必改 FastAPI 路由 |

事件轮次**默认按注入规程执行**；是否再 `read_skill(events)` 可选，不作为必经步骤。

内置样板取向：

| type | 文件 | 处理取向 |
|------|------|----------|
| `locker.created` | `locker-created.md` | 核对列表可见性与小区绑定 |
| `locker.offline` | `locker-offline.md` | 诊断与建议，禁止擅自改设备 |
| `order.refund` | `order-refund.md` | 总结为主，默认不执行退款写操作 |

---

## 会话与历史

- 触发消息：`role=user`，`source=event`，正文含事件头 + 业务数据 + 规程  
- Agent 回复：与对话轮相同，写入 assistant（含 thought / tools metadata）  
- 示例站历史 API 会带出 `source`；前端对 `event` 显示「事件」标签  
- 事件轮默认 `present_mode=markdown`（MVP 不做 AG-UI 流式推屏）

---

## 本地联调

1. `events.enable: true`，配置 `shared_secret`  
2. 重启 `main.py`  
3. `GET /v1/events/types` 确认分册已加载  
4. 使用真实业务数据与 Token（脚本会自动生成新 `event_id`）：

```bash
export HUBLOOM_BEARER_TOKEN='业务 Token'
export HUBLOOM_SESSION_ID='demo-session'
./examples/chat/scripts/post_locker_created.sh
```

脚本默认 payload 为钥匙柜样例字段；可用环境变量覆盖设备号/小区名等（见脚本头注释）。

验收时建议核对：

1. 响应 `ok: true` 且 `duplicate: false`  
2. 历史用户气泡含 `【事件处理规程 · locker-created.md】`  
3. 工具链出现分册要求的 list/call（如钥匙柜 / 小区 GetList）  
4. 重复同一 `event_id` → `duplicate: true`，summary 不变  

---

## 代码索引

| 路径 | 职责 |
|------|------|
| `src/events/models.py` | 入站规范化 |
| `src/events/catalog.py` | 扫分册、渲染触发文案 |
| `src/events/dispatcher.py` | 幂等、调 Runtime、可选回调 |
| `src/events/idempotency.py` | 进程内 `event_id` 结果表 |
| `skills/events/` | 总则 + 分册玩法 |
| `examples/chat/app.py` | HTTP 入口 |
| `examples/chat/scripts/post_locker_created.sh` | 联调脚本 |
| `tests/test_events.py` | 契约 / 扫描 / 幂等 / 鉴权 |

---

## 非目标（当前 MVP）

- 每业务 API 一条 Hubloom 路由、或把 `/v1/events` 做成 Swagger 业务接口  
- 事件轮 AG-UI 流式推到已打开的聊天页（历史刷新可见即可）  
- 跨进程持久化幂等表、MQ / Cron 入站  
- IM 通道主动触达  

以上能力可在本契约稳定后按路线图叠加。
