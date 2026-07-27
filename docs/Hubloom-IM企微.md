# Hubloom IM：企业微信对话入口

把**企业微信自建应用**做成与网页对等的对话入口：用户在应用里发文字 → Hubloom 调业务接口换 Token → 跑 Agent → 用应用消息把 Markdown 推回企微。

实现：`src/im/wecom/`；示例站：`GET/POST /v1/im/wecom/callback`。

---

## 定位

| 问题 | 说明 |
|------|------|
| 通道 | 自建应用**单聊**（不是群机器人） |
| 回复 | 仅 Markdown / 文本；不做 A2UI 面板 |
| 会话 | `session_id = wecom:{企微UserId}`（网页历史可查同一会话） |
| 业务鉴权 | **必须**经 `token_resolve` 调业务接口，用企微账号换 Bearer Token |
| 与事件 | `/v1/events` 仍是业务推送；本页是**人在企微里对话** |

---

## 主链路

```text
企微用户发文字
  → 企微服务器 POST /v1/im/wecom/callback（加密 XML）
  → Hubloom 验签解密、MsgId 排重
  → 立刻 HTTP 200 空串（满足 5 秒限制）
  → 异步：
       1) POST/GET 业务 token_resolve（wecomUserId → accessToken）
       2) 未绑定 → 主动推送提示，不跑 Agent
       3) 已绑定 → run_stream(session=wecom:uid, bearer_token=…)
       4) message/send 推 Markdown 结论
```

Agent 与网页共用 `HubloomRuntime` 与运行锁；`present_mode=markdown`。

若本轮产生表单（A2UI），回复中附加提示：请到 Web 对话页打开同一 `session_id` 完成填写。

本地联调时公网段通常是：

```text
企微 → HTTPS 临时隧道（cloudflared）→ 本机 :8010 → 同上异步流程
                                         ↓
                              token_resolve 可打本机 mock
                                         ↓
                              Hubloom → qyapi.weixin.qq.com（出站需可信 IP）
```

---

## 本地联调：完整配置流程

按下面顺序做；任一步跳过都容易出现「保存失败 / 有回调无回复」。

### 1. 企微侧：创建自建应用

在**网页管理后台**（非手机）创建自建应用（例如 Hubloom），记下：

| 项 | 用途 |
|----|------|
| 企业 ID（`corp_id`） | 加解密 + gettoken |
| 应用 Secret（`corp_secret`） | gettoken / message/send |
| AgentId（`agent_id`） | 推送消息指定应用 |
| 回调 Token / EncodingAESKey | 与「接收消息」页一致，填进 `env.yaml` |

「接收消息」先不要点保存，等本机服务 + 公网隧道就绪后再填 URL。

### 2. 本机：`config/env.yaml`

两类地址**不要混**：

| 配置位置 | 填什么 |
|----------|--------|
| 企微后台「接收消息」URL | `https://<公网>/v1/im/wecom/callback` |
| `im.wecom.token_resolve.url` | **业务换票接口**，不是回调 URL |

本地暂无真实业务换票时，可用示例站 mock：

```yaml
im:
  wecom:
    enable: true
    corp_id: wwxxxxxxxx
    corp_secret: ...
    agent_id: 1000002
    token: ...                    # 与后台「Token」一致
    encoding_aes_key: ...         # 43 字符，与后台一致
    session_prefix: wecom
    # 仅本地：/v1/dev/wecom-token 原样返回（填网页对话用的业务 Bearer）
    # 有真实换票接口后删除本项，并把 token_resolve.url 改成业务地址
    dev_bearer_token: eyJ...
    token_resolve:
      url: http://127.0.0.1:8010/v1/dev/wecom-token
      method: POST
      body_template: '{"wecomUserId":"{wecom_userid}"}'
      token_path: accessToken
      unbound_http_statuses: [404]
```

`enable=true` 时须配齐企微凭证 + `token_resolve.url`，否则进程启动失败。

### 3. 启动 Hubloom

```bash
# 仓库根目录，默认 :8010
.venv/bin/python main.py
```

自检：`curl -s http://127.0.0.1:8010/health` → `{"status":"ok"}`。

### 4. 暴露公网 HTTPS（cloudflared）

企微回调必须 HTTPS。本地常用：

```bash
cloudflared tunnel --url http://127.0.0.1:8010
```

记下输出的 `https://xxxx.trycloudflare.com`。隧道与 Hubloom **需同时保持运行**；重启 Hubloom 时若隧道先连不上，会出现短暂 `connection refused`（可忽略，服务起来后即可）。

### 5. 企微后台：保存「接收消息」

1. URL：`https://xxxx.trycloudflare.com/v1/im/wecom/callback`（路径须完整到 `wecom/callback`）
2. Token / EncodingAESKey 与 `env.yaml` **完全一致**
3. 「用户发送的普通消息」一般为**已勾且灰色不可取消**（强制开启，正常）
4. 点**保存**：企微会 **GET** 打回调做 URL 验证；成功即配置生效

### 6. 企业可信 IP（出站推送）

回调是**企微 → 你的公网**；主动回复是 **你的机器 → `qyapi.weixin.qq.com`**。

若 Agent 已跑完、网页历史有回复，但手机无气泡，查 `logs/debug.log`：

```text
errcode=60020  not allow to access from your ip  from ip: x.x.x.x
```

到管理后台应用详情的 **企业可信 IP**，把日志中的出口 IP 加上后保存，再发一条消息即可（一般不必改代码、不必重启）。家宽 IP 变更后需重新添加。当前出口可用 `curl -s ifconfig.me` 查看。

### 7. 手机验证

1. 企业微信 App → 工作台 → 打开该自建应用  
2. 发普通文字（如「你好」）  
3. 数秒内应收到 Markdown；文末可带 `会话 wecom:<UserId>（网页历史可查）`  
4. 网页用同一 `session_id`（如 `wecom:ZhongYuJian`）应能看到相同历史  

成功时本机日志大致为：

```text
POST /v1/im/wecom/callback ... 200
POST /v1/dev/wecom-token ... 200   # 使用本地 mock 时
# Agent 跑完后 message/send 成功（无 60020）
```

---

## 配置（生产形状）

有真实业务换票后，去掉 `dev_bearer_token`，例如：

```yaml
im:
  wecom:
    enable: true
    corp_id: wwxxxxxxxx
    corp_secret: ...
    agent_id: 1000002
    token: ...
    encoding_aes_key: ...
    session_prefix: wecom
    token_resolve:
      url: https://biz.example/api/app/account/token-by-wecom
      method: POST
      body_template: '{"wecomUserId":"{wecom_userid}"}'
      token_path: accessToken
      # headers:
      #   Authorization: "Bearer {service_token}"
      # service_token: ...
      unbound_http_statuses: [404]
      # unbound_codes: ["40001"]
```

回调 URL 改为稳定公网域名上的 `/v1/im/wecom/callback`；企业可信 IP 改为服务器出口 IP。

### 业务换 Token 约定（最小）

```http
POST /api/app/account/token-by-wecom
Content-Type: application/json

{"wecomUserId":"zhangsan"}
```

成功：

```json
{"accessToken":"eyJ..."}
```

未绑定：HTTP `404`（或配置 `unbound_codes` 匹配业务错误码）。

字段名可通过 `body_template` / `token_path` 调整（也支持 `data.accessToken`）。

本地 mock：`POST /v1/dev/wecom-token` → `{"accessToken":"<im.wecom.dev_bearer_token>"}`（仅联调，勿用于生产）。

---

## HTTP

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/v1/im/wecom/callback` | URL 验证：解密 `echostr` 原样返回 |
| POST | `/v1/im/wecom/callback` | 收消息：验签后空串 200，异步处理 |
| POST | `/v1/dev/wecom-token` | 本地换票 mock（需 `dev_bearer_token`） |

`im.wecom.enable=false` 时回调返回 503。

---

## 排重与失败提示

- **MsgId** 进程内排重，避免企微重试双跑 Agent  
- 未绑定 / 换 Token 失败：主动推中文说明，不调用业务 MCP  
- Agent 异常：推送短错误文案  
- 推送失败（含 `60020`）：见 `logs/debug.log`；网页会话可能已有回复  

---

## 联调检查清单

1. Hubloom `:8010` 与 cloudflared（或其它隧道）同时在跑  
2. GET 回调验证通过（企微后台保存成功）  
3. `token_resolve.url` 指向换票接口 / 本地 mock，**不是**回调 URL  
4. 企业可信 IP 已包含本机当前出口（避免 `60020`）  
5. 已绑定用户发文字 → 数秒后手机收到 Markdown  
6. 网页历史用 `wecom:<UserId>` 能看到同一会话  
7. 未绑定用户 → 收到绑定提示，不跑业务 MCP  
8. 重复投递同一 MsgId 不产生两轮 Agent  

---

## 代码索引

| 路径 | 职责 |
|------|------|
| `src/im/wecom/crypto.py` | 签名 / AES 加解密 |
| `src/im/wecom/client.py` | gettoken、message/send |
| `src/im/wecom/token_resolve.py` | 业务换 Token |
| `src/im/wecom/adapter.py` | 回调编排、排重、跑 Agent |
| `examples/chat/app.py` | 回调路由 + `/v1/dev/wecom-token` |
| `tests/test_wecom.py` | 官方向量与适配器单测 |

---

## 非目标（本期）

- 群机器人、钉钉 / 飞书  
- 企微内 A2UI / 卡片审批  
- 语音、图片消息  
- 事件跑完后自动推企微（可复用 `WeComAppClient`，二期再挂）  
