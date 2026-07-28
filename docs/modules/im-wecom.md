# 企业微信（IM）

## 企业微信介绍

网页对话的起点是人在浏览器里打字。运维、客服、业务同事日常却更常泡在**企业微信**里：手机上一句「帮我查一下 A 区柜子」，若还要切到 Hubloom 网页才能问 Agent，门槛就高了。  
**企业微信入口要解决的，就是让同一个人在企微自建应用里也能跟同一套 Agent 对话**：成员发文字 → 企微把加密回调推到 Hubloom → 验签解密 → 按企微账号换成业务 Bearer → 用约定好的会话 id 跑一轮编排 → 再把 Markdown 结果用应用消息推回手机。人不换入口，能力也不另起一套。

可以把它理解成：**同一套 Agent，换了一扇门。** 网页门吃的是浏览器里的自然语言和 SSE；企微门吃的是回调 XML 和应用消息 API。后面的推理、工具、记忆，尽量复用 Runtime，而不是在 IM 模块里再写一个「企微专用大脑」。事件入口（Events）也是换门，但那边是业务系统推结构化通知；这边是人对人说话，只是通道换成了企微。

这条路上有几件必须先想清楚的事。企微要求回调尽快应答（大约数秒内），而跑一轮 Agent 往往更慢，所以正式路径通常是：先空 200 确认收到，再异步处理、主动推送结果——不能卡在「等模型说完再回 HTTP」。成员发的同一条消息也可能被重试，要用消息 id 做去重，避免同一句话跑两轮。企微 UserId 和业务系统里的登录态也不是一回事，中间要有一次「换票」：用 UserId 去业务接口换 Bearer，Agent 调 MCP 时才带得上权限；本地联调可以用 mock 接口，生产必须指到真实换票地址。会话要落在稳定的键上，例如 `wecom:{UserId}`，这样网页历史和企微里聊的是同一条线，人事后打开对话页还能对得上。

整体上可以记三句：  
**入口换成企微回调与应用消息；身份靠换票接到业务 Token；执行仍走同一套 Agent。**  
IM 层自己负责加解密、去重、换票、推送和会话键约定——不管前端怎么画，也不把钉钉、飞书一次做完。当前 MVP 以文字为主，表单/卡片等放在路线图的 IM 增强里。

读完上面，你应能说清：企微入口解决什么问题、和网页 / Events 差在哪、为什么要异步推送和换票。下一节讲这些需求如何落成取舍；再往后是不经 Agent 的收发联调，方便先把管道跑通。

---

## 设计思路

最容易走偏的做法，是在 IM 里另写一套对话引擎：自己拼提示、自己调业务、自己决定回复格式。那样会和网页路径分叉，工具面和记忆都要维护两份。Hubloom 反过来：`WeComChatAdapter` 只做通道适配——验签解密、去重、换票、调用注入进来的 `run_agent`、把结果 `send_markdown` 推回——真正办事仍走 Runtime 的 `run_stream`。代价是企微侧的体验受 Agent 快慢影响；收益是网页会的，企微里也能用。

回调协议上也故意拆开。企微推来的是加密包，必须用 Token、EncodingAESKey、企业 corp_id 按官方算法验签解密，这一层放在 `crypto`，与「怎么跑 Agent」无关。主动发消息走应用 `gettoken` + `message/send`，放在 `client`，网页对话根本用不到这套 API。适配器把两段粘起来，但测试时可以只用 client 做 send、或只用 crypto+client 做 echo，**不经 Agent 也能验证管道**——这正是本章后面动手脚本的设计动机：先证明「收得到、发得回」，再接换票和编排，排障时不会把密钥错误和模型错误混在一起。主动推送还受企微「企业可信 IP」约束：cloudflared 只解决回调打进来，本机调 `message/send` 仍走宽带公网 IP，白名单要单独配。

身份上不假设企微 UserId 能直接当业务 Token。正式路径通过可配置的 `token_resolve` HTTP 去换 Bearer；未绑定账号时给用户一句人话提示，而不是让 Agent 带着空权限去调 API。本地可以用示例站的 mock 换票地址加 `dev_bearer_token` 顶上。会话键用 `wecom:{UserId}`（前缀可配），与网页 `session_id` 同一套记忆隔离语义——产品上一人一会话，Web 与企微若共用同一键，就不能靠「只给企微加全局锁」了事。

同用户连发、多实例重试，不能只靠进程内字典。IM 模块已落地 **按 session 的 Redis 队列**（`im/session_queue`）：入站先入队并尽快 ACK，再由持锁的 Worker FIFO **一条一条**消费；MsgId 走 Redis 幂等键。适配器可选注入该队列（注入后 `schedule_handle_message` 走入队）；未注入时仍保留进程内 `create_task`，方便示例站尚未改装配时继续跑。队列 Handler 与取任务接口使用 `list[SessionJob]`，并留有 `merged_from`、`request_cancel` / `active` 等扩展点——当前不做多条合并与打断，但以后加上时不必换存储模型。Web / 示例站接同一套队列是后续装配，本期先把 IM 侧能力与对外 API 备好。

HTTP 路由留在示例站（或联调脚本自己起的最小服务），`src/im/wecom` 与 `session_queue` 保持可嵌入：换主机、换端口、配 cloudflared 公网 HTTPS，都是部署问题，不是模块内核。企微要求接收消息 URL 必须是 HTTPS，本地开发用临时隧道是务实做法。当前只认真支持文字；图片等类型先回一句「请发文字」，表单与卡片推送留给后续 IM 增强。

---

## 本章怎么读

介绍与设计思路之后，先用最小脚本做**不经 Agent** 的收发联调（send / echo），再用 `queue` 验证 Redis 会话串行；需要完整对话时再接示例站与 Runtime（示例站接队列尚待装配）。进阶后台与可信 IP 等见：[企业微信入口](../advanced/wecom-integration.md)。

---

## 最小动手：不经 Agent 的收发联调

脚本：[`tests/test_im_wecom.py`](../../tests/test_im_wecom.py)。

两种模式，都**不**换业务票、**不**跑 Agent：

| 模式     | 方向               | 作用                                                   |
| -------- | ------------------ | ------------------------------------------------------ |
| **send** | 本机 → 企微        | `gettoken` + `message/send`，手机应用能收到一条消息    |
| **echo** | 企微 → 本机 → 企微 | 起回调服务：解密打印收到的内容，再主动回推一条固定文案 |

### 前置配置

在 `config/env.yaml`（或 `HUBLOOM_CONFIG`）里打开并填好 `im.wecom`：

```yaml
im:
  wecom:
    enable: true
    corp_id: ...
    corp_secret: ...
    agent_id: 1000002
    token: ... # 与企微后台「接收消息」Token 一致
    encoding_aes_key: ... # 43 字符，与后台一致
```

- **send** 至少需要：`corp_id` / `corp_secret` / `agent_id`
- **echo** 额外需要：`token` / `encoding_aes_key`（回调验签解密）
- 接收人用企微通讯录里的 **UserId**（如 `ZhongYuJian`），不是昵称

密钥只放本地配置，**不要提交仓库**。字段说明见 [`config/env.example.yaml`](../../config/env.example.yaml)。

---

### 案例 A：本机主动发到企微（send）

在仓库根目录：

```bash
PYTHONPATH=src .venv/bin/python tests/test_im_wecom.py send \
  --to 你的UserId --text "联调：你好"
```

也可用环境变量：`WECOM_TO_USER=你的UserId`。

**成功时终端类似：**

```text
【模式】 send（本机 → 企微，不经 Agent）
【配置】 .../config/env.yaml
【应用】 agent_id= 1000002 corp_id= ww….…
【接收人】 ZhongYuJian
【gettoken】 ok，access_token 长度 214
【发送】 markdown …
【结果】 {'errcode': 0, 'errmsg': 'ok', 'msgid': '...'}
请到企业微信里看该应用是否收到上述消息。
```

读法：`gettoken` 成功说明应用凭证可用；`errcode: 0` 说明消息已交给企微。打开手机企业微信，在该自建应用会话里应看到「联调：你好」。

若 `81013` 一类「user invalid」：多半是 UserId 写错，或该成员不在应用可见范围。

---

### 案例 B：企微发来、本机收到并回推（echo）

需要**两个终端**，外加企微后台把回调指到公网 HTTPS。

**终端 1 — 回声服务**

```bash
PYTHONPATH=src .venv/bin/python tests/test_im_wecom.py echo --port 8765
```

应看到：

```text
【模式】 echo（企微 → 本机解密打印 → 主动回推，不经 Agent）
【监听】 http://0.0.0.0:8765/v1/im/wecom/callback
...
Uvicorn running on http://0.0.0.0:8765
```

**终端 2 — 临时公网隧道**（本机已装 `cloudflared` 时可直接用）

```bash
cloudflared tunnel --url http://127.0.0.1:8765
```

日志里会出现类似：

```text
https://xxxx.trycloudflare.com
```

把企微管理后台该应用的「接收消息」URL 设为：

```text
https://xxxx.trycloudflare.com/v1/im/wecom/callback
```

Token / EncodingAESKey 与 `env.yaml` 里一致，保存。后台会先打 **GET** 做 URL 验证。

**验证 + 收信成功时，终端 1 类似：**

```text
【URL 验证】 ok，echo= ...
GET /v1/im/wecom/callback?... 200 OK
【收到】 {'FromUserName': 'ZhongYuJian', 'MsgType': 'text', 'MsgId': '...', 'Content': '你好'}
POST /v1/im/wecom/callback?... 200 OK
【回推】 markdown ok → ZhongYuJian
```

读法：

1. **【URL 验证】ok** — 加解密与后台配置一致，回调地址通
2. **【收到】** — 企微已把成员消息推到本机，明文已解开
3. **【回推】ok** — 本机又用应用消息 API 推回手机（固定 echo 文案，不是 Agent 回复）

手机侧应先后看到：你发的「你好」，以及一条「Hubloom echo（无 Agent）已收到…」类回复。

注意：`cloudflared tunnel --url` 是**临时隧道**，关掉后域名失效，需重新开隧道并改企微 URL。两个进程都要保持运行。

---

### 和正式入口的差别

|              | 本脚本（send / echo）      | 示例站正式路径                             |
| ------------ | -------------------------- | ------------------------------------------ |
| 目的         | 验管道：凭证、加解密、推送 | 真对话                                     |
| Agent        | 不跑                       | `run_stream` 一轮                          |
| 换业务 Token | 不换                       | `token_resolve` / 本地 `dev_bearer_token`  |
| HTTP         | echo 自带最小回调          | `examples/chat` 的 `/v1/im/wecom/callback` |

管道跑通后，再起示例站、把回调指到同一路径（或换端口与隧道），才会走「收信 → 换票 → Agent → 推回」。

---

## Redis 会话队列（IM 模块已落地）

按 **session（用户）** 串行的入站队列在 `im/session_queue/`，**不依赖 Runtime / 示例站**。当前行为是一条一条处理；Handler 与 `take_jobs` 使用 `list[SessionJob]`，并预留 `merged_from` / `request_cancel`，后期合并或打断不必换存储模型。

### 对外用法

```python
from im import SessionJob, SessionWorker, create_session_queue

queue = create_session_queue(redis_url="redis://localhost:6379/0")

async def handle_jobs(jobs: list[SessionJob]) -> None:
    # 现在 len(jobs)==1；后期合并时可能多条
    job = jobs[0]
    ...

worker = SessionWorker(queue, handle_jobs)
await worker.enqueue_and_kick(
    SessionJob(
        session_id="wecom:ZhongYuJian",
        source="wecom",
        text="你好",
        dedupe_key="msgid-optional",
        meta={"wecom_userid": "ZhongYuJian"},
    )
)
```

企微适配器可选注入同一套队列（示例站尚未改装配时仍走进程内 `create_task`）::

```python
from im import create_session_queue
from im.wecom import WeComChatAdapter

queue = create_session_queue(redis_url=...)
adapter = WeComChatAdapter(
    ...,
    session_queue=queue,  # 注入后 schedule_handle_message → Redis 入队
)
```

也可用 `wecom_message_to_job(...)` / `adapter.enqueue_message(msg)` 自行入队。

本地只验队列（需 Redis，不连企微）::

```bash
PYTHONPATH=src .venv/bin/python tests/test_im_wecom.py queue
```

### Redis 键

| 键 | 作用 |
| --- | --- |
| `hubloom:im:q:{session_id}` | 待处理 List |
| `hubloom:im:processing:{session_id}` | 在途（防崩溃丢任务） |
| `hubloom:im:lock:{session_id}` | 消费者锁 |
| `hubloom:im:dedupe:{key}` | MsgId 等幂等 |
| `hubloom:im:active:{session_id}` | 当前 Job（供后期打断） |
| `hubloom:im:cancel:{session_id}` | 取消标记（API 已暴露，主路径暂不自动打断） |

---

## 代码锚点

| 路径 | 职责 |
| --- | --- |
| `im/session_queue/` | Redis 会话队列 / Worker / Job |
| `im/wecom/crypto.py` | 回调验签、加解密、明文 XML 解析 |
| `im/wecom/client.py` | `gettoken`、应用消息 text / markdown |
| `im/wecom/adapter.py` | 适配器；可选 Redis 入队 |
| `im/wecom/token_resolve.py` | 企微 UserId → 业务 Bearer |
| `tests/test_im_wecom.py` | send / echo / queue |
| `examples/chat/app.py` | 挂 Runtime 的完整回调（尚未接队列） |

---

## 延伸阅读

- 进阶：[企业微信入口](../advanced/wecom-integration.md)
- 同进程装配：[Runtime](runtime.md) · [示例站](examples-chat.md)
