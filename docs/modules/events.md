# Events

## Events 介绍

日常用 Hubloom 时，最常见的路径是：用户在对话里发一句，Agent 再思考、调工具、回答。整条链路的起点是**人**。

但业务现场还有另一类需求：事情已经在业务系统里发生了——新钥匙柜登记完成、设备突然离线、订单发起退款——运维或客服未必正好盯着聊天窗口。若只能等人来问「帮我核对一下刚才那台柜」，Agent 再能干，也只能被动待命。  
**Events 要解决的，就是让业务系统也能「开口」**：系统把一件已发生的事推给 Hubloom，Hubloom 按事先写好的处理规程，**主动跑一轮 Agent**，把核查、说明或建议写进对应会话，必要时再通知业务方。人不在线时，自动化处理也能先走完；人之后打开对话，能看到这件事已经处理过（页面上通常会有「事件」一类标记）。

所以可以把它理解成：**同一套 Agent 能力，换了一种入口**。对话入口吃的是用户自然语言；事件入口吃的是结构化业务通知（事件类型、业务字段、落到哪条会话）。后面的推理、读规程、调业务 API、写会话历史，尽量复用已有 Runtime / Agent，而不是另起一套「事件专用大脑」。

具体会碰到几件必须设计清楚的事。

第一，**业务通知不可靠地只发一次**。Webhook、网关、上游重试都可能导致同一条业务事实被推多次。若每次都跑 Agent，就会重复查库、重复写历史、甚至重复副作用。因此每条事件要带一个稳定的 **`event_id`**：同一个 id 只真正执行一次，重放时直接返回「已处理过」（幂等）。这是正确性，不是性能彩蛋。

第二，**同一条会话上可能连续涌入多件事**。若两个事件并行抢同一条对话线，历史会交错、工具调用会打架。因此用 **`session_id` 标识会话线**：同一会话上的事件排队串行；不同会话之间可以并行。用户量上来时，吞吐主要来自「很多不同会话同时跑」，而不是「同一会话里无限并行」。

第三，**不同类型的事，规矩不一样**。登记核对、离线排查、退款说明，步骤和禁区都不同。Hubloom 不把这些硬编码进调度器，而是写在 `skills/events/` 下的分册里：有类型名、必填业务字段、以及「该怎么做 / 不该做什么」的正文。事件进来后，系统找到对应分册，把规程和业务数据拼成一轮触发文，再交给 Agent——模型按规程办事，而不是自由发挥总结一句就收工。

第四，**结果要落在人找得到的地方**。处理结论进入该 `session_id` 的会话记忆；打开对话刷新历史即可看到。也可配置一个结果回调地址，把摘要回传给业务系统。当前实现里，若用户正开着页面，并不会像聊天 SSE 那样实时「推屏」——那是后续增强，不是现在这条 MVP 链路的一部分。

整体上，Events 的设计意图可以概括成三句话：  
**入口换成业务推送；规矩放在事件分册；执行仍走同一套 Agent。**  
调度层自己只做规范化、类型校验、Redis 幂等、会话串行、拼触发文和可选回调——不管前端怎么画、不管业务 API 怎么实现、也不假装自己是消息队列或定时任务系统。消息队列入站、定时告警、打开会话时主动推屏等，属于路线图里的「事件驱动增强」，本章后半的代码地图对应的是**已经落地的 Webhook MVP**。

读完上面，你应能用自己的话回答：Events 解决什么问题、和聊天入口差在哪、为什么要有 `event_id` 与 `session_id`、规程写在哪里、结果去了哪里。下一节讲这些需求如何落成具体取舍；再往后才是代码地图。

---

## 设计思路

介绍里说的是「要解决什么」。这一节说的是：**为什么建成现在这样，而不是另一种样子**。

### 1. 做入口适配，不做第二套 Agent

最容易走偏的路是：事件来了，另写一套「事件处理器」——自己拼提示、自己调 API、自己决定何时结束。那样会和对话路径分叉，规程、工具面、记忆、呈现都要维护两份。

Hubloom 的选择是反过来的：Events 只负责把业务通知变成**一轮合法的 Agent 触发**（规范化、校验、幂等、串行、注入分册正文），真正办事仍走 `run_stream` 那条编排。  
代价是：事件处理的快慢、成败，都会受 LLM 与工具链路影响；收益是：对话里会的能力，事件里也能用，行为一致、可演进。

### 2. 规程外置到分册，调度器保持「傻」

登记核对和退款说明，步骤完全不同。若把 if/else 写进 `dispatcher.py`，每加一种业务都要改代码、发版。

因此类型与规程的真相源放在 `skills/events/*.md`：调度器只认 `type` → 找到分册 → 校验 `payload_fields` → 拼触发文。新增事件类型优先加文档，而不是改 Python。  
YAML `events.catalog` 只作覆盖/补洞，不取代分册作为主真相源——避免「配置里一份、skills 里又一份」长期漂移。

### 3. 幂等按事件，串行按会话——两把锁各管一件事

容易混的一点是：用 `session_id` 做幂等，或用全局队列串行所有事件。

- **幂等键必须是 `event_id`**：同一业务事实的重试应对齐到「这件事」，而不是「这个人」。同一会话完全可以先后处理多件不同的事。
- **串行粒度必须是 `session_id`**：保护的是同一条对话线的历史与工具互斥；不同会话并行才是扩容方向。全局单队列会把无关用户堵在一起，性价比很差。

实现上两者都落到 Redis：多实例部署时，进程内字典挡不住跨进程重放，也锁不住跨进程的同会话并发。曾考虑过的内存方案只适合单进程演示，正式路径只保留 Redis。

同 `event_id` 在进程内还有一层 inflight 等待：避免「结果尚未 `put` 进 Redis 时，并发请求各自开跑」。跨实例主要仍靠幂等键最终收敛；inflight 是热路径上的补强，不是分布式事务。

### 4. 用 Protocol 接 Agent，而不是 import Runtime

若 `events` 直接依赖 `HubloomRuntime`，很快会和 runtime / 示例站缠成环：测调度要拉起整份配置，换宿主（别的 `run_stream` 实现）也麻烦。

因此 Dispatcher 只依赖 `EventAgentRunner`（「给我跑完一轮，返回 `RunResult`」）。示例站用 `StreamHostAgentRunner` 把 Runtime 包进去；单测可以用 FakeAgent 只验证幂等与串行。  
`bind_runtime` 仍保留作兼容，新代码优先 `bind_agent`。

### 5. HTTP 留在示例站，模块保持可嵌入

`POST /v1/events`、密钥头、`events.enable` 开关属于**某一种部署形态**。`src/events/` 刻意不绑 FastAPI，方便嵌进自有后端：自己解析 JSON，调用 `normalize_event` + `dispatch` 即可。

### 6. 同步 Webhook 先跑通，异步与推屏往后放

当前是同步语义：请求进来，尽量跑完再返回结果（含 `duplicate` / `summary`）。这对联调、幂等验证都简单。  
高峰时 HTTP 会堆在 Agent 耗时上——这是已知边界。消息队列削峰、定时入站、打开会话主动推屏、回调重试与签名等，属于「事件驱动增强」，不塞进 MVP，以免调度层同时变成 MQ 客户端和实时推送中枢。

一句话对照：

| 若做成… | 我们选择… | 主要理由 |
| --- | --- | --- |
| 事件专用执行引擎 | 复用 Agent 一轮 | 能力与对话一致 |
| 规程写在代码里 | `skills/events` 分册 | 加类型少改代码 |
| 按 session 幂等 / 全局串行 | `event_id` 幂等 + `session_id` 串行 | 语义对齐真实约束 |
| 进程内字典 | 仅 Redis | 多实例正确 |
| Dispatcher 依赖 Runtime | `EventAgentRunner` | 解耦、可测、可替换 |
| 模块内置 HTTP + MQ + 推屏 | 模块只调度；HTTP 在示例站 | 边界清晰，增强可叠加 |

---

## 本章怎么读

本章其余部分是 **`src/events/` 的代码地图**：Webhook 事件规范化 → Redis 幂等与会话串行 → 注入分册 → 跑一轮 Agent；可选回调业务方。

HTTP 路由在示例站（`POST /v1/events`），本模块不依赖 FastAPI。调度层通过 `EventAgentRunner` 注入「跑一轮」能力；示例站用 `StreamHostAgentRunner` 包装 Runtime。

读完应能指出：改契约看哪、改幂等/串行看哪、加事件类型改哪、Dispatcher 怎么接到 Agent。

---

## 一句话职责

> **Webhook 事件 → Redis 幂等（`event_id`）→ Redis 会话串行（`session_id`）→ 注入分册 → Agent 一轮。**

装配最小形：

```python
dispatcher = EventDispatcher(
    catalog=catalog,
    idempotency=create_idempotency_store(redis_url=url),
    session_gate=create_session_gate(redis_url=url),
)
dispatcher.bind_agent(StreamHostAgentRunner(host))  # host 提供 run_stream
result = await dispatcher.dispatch(event)
```

---

## 边界（管什么 / 不管什么）

| 管                                      | 不管（链走）                                                |
| --------------------------------------- | ----------------------------------------------------------- |
| `HubloomEvent` 规范化、payload 必填校验 | HTTP / SSE / 鉴权头解析 → [示例站](examples-chat.md)        |
| 从 `skills/events/*.md` 发现类型与规程  | 通用 Skill 名片 / `read_skill` → [Skill](skill.md)          |
| Redis 幂等、同 session 串行锁           | Think / Present / Respond 编排 → [Agent](agent.md)          |
| 拼触发文、调用 `EventAgentRunner`       | 业务 API 怎么调 → [Tools](tools.md) · [MCP](mcp-adapter.md) |
| 可选 `result_callback` HTTP POST        | MQ / 定时入站、打开会话推屏（路线图「事件驱动增强」）       |

Events **不是**消息队列消费者，也**不是**前端推送通道；它是「业务推一条 → 同一套 Agent 跑一轮」的入站适配。

---

## 关键入口与目录

| 路径                     | 职责                                                 |
| ------------------------ | ---------------------------------------------------- |
| `events/models.py`       | `HubloomEvent`、`normalize_event`                    |
| `events/catalog.py`      | 扫描分册、`EventCatalog`、`render_event_trigger`     |
| `events/idempotency.py`  | `RedisIdempotencyStore`（仅 Redis）                  |
| `events/session_gate.py` | `RedisSessionGate`（仅 Redis）                       |
| `events/agent_runner.py` | `EventAgentRunner` Protocol、`StreamHostAgentRunner` |
| `events/dispatcher.py`   | `EventDispatcher.dispatch` 主路径                    |
| `events/callback.py`     | 可选结果回调                                         |
| `events/__init__.py`     | 对外导出                                             |
| `skills/events/*.md`     | 事件类型真相源（frontmatter `event:` + 规程正文）    |
| `examples/chat/app.py`   | 装配 Dispatcher、`POST /v1/events`                   |
| `tests/test_events.py`   | Redis 幂等 + 同 session 串行演示                     |

---

## 主调用链

```text
POST /v1/events（示例站）
    │  normalize_event
    ▼
EventDispatcher.dispatch
    │  catalog.get(type) + payload_fields 校验
    │  idempotency.get → 已有则 duplicate=True 返回
    │  进程内 inflight（同 event_id 并发占坑）
    │  session_gate.run(session_id)   ← Redis 锁，同会话排队
    │      └─ agent.run_event_turn(触发文 Message, trigger_source="event")
    │  idempotency.put(result)
    │  可选 post_result_callback
    ▼
EventDispatchResult
```

并发语义（实现约束，不是口号）：

| 情况                             | 行为                                      |
| -------------------------------- | ----------------------------------------- |
| 同 `event_id` 重放               | 不跑 Agent，`duplicate=True`              |
| 同 `session_id`、不同 `event_id` | Redis 锁排队串行，不丢                    |
| 不同 `session_id`                | 可并行                                    |
| 事件类型多少                     | 只影响 catalog 扫描；吞吐瓶颈在 Agent/LLM |

Redis 键：

| 能力   | 键                                        |
| ------ | ----------------------------------------- |
| 幂等   | `hubloom:event:idem:{event_id}`           |
| 会话锁 | `hubloom:event:lock:session:{session_id}` |

默认 Redis：`HUBLOOM_EVENTS_REDIS_URL` 或 `redis://localhost:6379/0`。

---

## 事件类型从哪来

真相源是 `skills/events/` 下带 frontmatter 的分册（跳过 `SKILL.md` / `README.md`）：

```yaml
---
event: locker.created
title: 钥匙柜已登记
description: ...
payload_fields:
  - deviceId
hint_tags:
  - VehicleKeySmartLocker
---
# 规程正文（步骤 / 禁止 / 完成标准）
```

`EventCatalog.load(events_dir=..., config_catalog=...)`：先扫分册，再被 `env.yaml` 的 `events.catalog` 同名覆盖/追加。  
`GET /v1/events/types`（示例站）列出当前已知 `type`。

新增类型：加一份分册 md → 重启进程即可（不必改 Dispatcher）。

---

## 和上下游的关系

```text
业务系统                    Hubloom                         会话 / 业务方
   │                          │                                │
   │  POST /v1/events         │                                │
   ├─────────────────────────►│ examples/chat                  │
   │                          │      │                         │
   │                          │      ▼                         │
   │                          │ EventDispatcher                │
   │                          │      │                         │
   │                          │      ├─ Redis 幂等/锁          │
   │                          │      ├─ catalog / 触发文       │
   │                          │      └─ StreamHostAgentRunner  │
   │                          │               │                │
   │                          │               ▼                │
   │                          │         Runtime.run_stream     │
   │                          │               │                │
   │                          │               ├─► memory（source=event）
   │                          │               └─► 可选 callback POST
```

| 上游 / 下游     | 关系                                                                                                              |
| --------------- | ----------------------------------------------------------------------------------------------------------------- |
| 示例站 HTTP     | 解析 body、校验 `X-Event-Secret`、调 `dispatch`                                                                   |
| Runtime / Agent | 被 `bind_agent` 注入；事件只是另一种 `trigger`                                                                    |
| Memory          | 结果落在事件的 `session_id` 历史；刷新对话页可见「事件」标记                                                      |
| Skill           | 分册在 `skills/events/`；总册仍可 `read_skill(skill='events')`                                                    |
| 配置            | `events.enable` / `shared_secret` / `result_callback_url` / `default_bearer_token` / `catalog`（`src/config.py`） |

---

## 本地验证

```bash
docker run -d --name redis -p 6379:6379 redis:7

HUBLOOM_EVENTS_REDIS_URL=redis://localhost:6379/0 \
  PYTHONPATH=src .venv/bin/python tests/test_events.py
```

关注：重放同 `event_id` → Agent 只调一次；并发同 session → 调用顺序串行。  
说明：该脚本用 FakeAgent，主要验证**调度**（幂等 / 串行），不会真调 LLM；端到端要走示例站 `POST /v1/events`。

---

## 延伸阅读

- 进阶契约与联调：[事件 Webhook](../advanced/webhook.md)
- 分册怎么写：[编写 Skill](../usage/write-skill.md)
- 路线图未做：MQ / 定时入站、回调完善、打开会话主动推屏（见根目录 README「事件驱动增强」）
