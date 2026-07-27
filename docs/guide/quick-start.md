# 5 分钟快速上手

本章目标：在本机跑通一条 **「对话 → 调真实 API」** 主路径。

配置已经就绪时，大约 **10～15 分钟**（含填 Key）。第一次接自己的 Swagger / 鉴权，按「半天内跑通」预期更稳妥。

装依赖或环境报错 → [安装与部署](installation.md)。  
还不清楚产品定位 → [Hubloom 是什么](what-is-hubloom.md)。

---

## 你将得到什么

完成后你应该能：

1. 后端在 `http://127.0.0.1:8010` 健康检查通过
2. 打开示例对话页（默认 `http://127.0.0.1:5173`）
3. 发一句话，看到 Markdown 回复；在 MCP 开启时能调到 OpenAPI 里的接口

---

## 开始之前

| 项           | 说明                                       |
| ------------ | ------------------------------------------ |
| Python 3.12+ | 推荐 [uv](https://github.com/astral-sh/uv) |
| Node.js      | 仅跑示例前端时需要                         |
| LLM API Key  | OpenAI 兼容接口（如 DeepSeek 等）          |
| OpenAPI 地址 | 自家 Swagger；没有时可用公开 Petstore 练手 |

下文命令均在**仓库根目录**执行。若尚未克隆：

```bash
git clone https://github.com/Zhong-y-j/Hubloom.git
cd Hubloom
```

---

## 步骤 1：安装依赖

```bash
uv sync
```

或：

```bash
pip install -r requirements.txt
```

---

## 步骤 2：最小配置

```bash
cp config/env.example.yaml config/env.yaml
```

编辑 `config/env.yaml`，至少填写（长期记忆 / RAG / 事件 / 企微先保持关闭或默认）：

```yaml
llm:
  api_key: sk-你的密钥
  model: 你的模型名 # 以网关实际名为准，例如 deepseek-v4-flash
  base_url: https://api.xxx.com # OpenAI 兼容 Base URL

mcp:
  enable: true
  # 练手：公开 Petstore；接业务时改成你的 Swagger JSON 地址
  swagger_url: https://petstore.swagger.io/v2/swagger.json
  # base_url: 一般可省略，由 spec 推断
  auth_scheme: Bearer
```

注意：

- **不要**把业务用户 Token 写进 `env.yaml`；在对话页或请求头传入。
- `config/env.yaml` 含密钥，仓库已 ignore，**勿提交**。

细讲：[配置 LLM](../usage/configure-llm.md) · [接入 Swagger](../usage/import-swagger.md)。

---

## 步骤 3：启动后端

```bash
PYTHONPATH=src:. uv run python main.py
```

看到 `Uvicorn running on http://0.0.0.0:8010` 即表示起来了。

另开终端自检：

```bash
curl -s http://127.0.0.1:8010/health
# 期望：{"status":"ok"}

curl -s http://127.0.0.1:8010/v1/mcp/status
# MCP 开启且 Swagger 加载成功时，应看到就绪相关字段（而非报错）
```

可选：打开 [http://127.0.0.1:8010/docs](http://127.0.0.1:8010/docs) 查看 API。

| 环境变量                              | 作用                                     |
| ------------------------------------- | ---------------------------------------- |
| `CORTEX_API_HOST` / `CORTEX_API_PORT` | 监听地址与端口（默认 `0.0.0.0:8010`）    |
| `HUBLOOM_CONFIG`                      | 配置文件路径（默认找 `config/env.yaml`） |

---

## 步骤 4：启动示例前端

再开一个终端：

```bash
cd examples/chat/web
npm install
npm run dev
```

浏览器打开 Vite 提示的地址（默认 [http://127.0.0.1:5173](http://127.0.0.1:5173)）。  
`/v1`、`/health` 会代理到 `:8010`。

在页面上：

| 字段              | 建议                                                                                                                                                 |
| ----------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------- |
| 用户 ID / Session | 任意，如 `demo-session`（多轮靠它隔离；页面也可能自动生成）                                                                                          |
| 业务 Token        | **有鉴权的业务 API**：填真实 Bearer。**Petstore 等公开接口**：界面可能写「可选」，但后端未配置静态 `mcp_token` 时仍可能要求请求头——请填占位如 `demo` |
| 呈现模式          | 可先用 `auto` 或 `markdown`；要看表单再试 `a2ui`                                                                                                     |

---

## 步骤 5：发第一句话

示例：

- Petstore：`列出可用的宠物相关接口` / `查一下宠物店里有哪些宠物`
- 自家 API：用你们业务里的真实说法，如「查询某某状态」

期望：

- 流式或完整的 **Markdown**；或右侧 **A2UI** 面板（视模式与模型）
- 需要调 API 时，过程中能看到工具调用（示例站通常可展开）

仅验后端可用：

```bash
curl -s http://127.0.0.1:8010/v1/chat \
  -H "Content-Type: application/json" \
  -H "X-Session-Id: demo-session" \
  -H "X-MCP-Token: demo" \
  -d '{"message":"你好，你能做什么？","stream":false,"present_mode":"markdown"}'
```

历史：

```bash
curl -s "http://127.0.0.1:8010/v1/chat/history?session_id=demo-session"
```

---

## 验收清单

- [ ] `/health` 返回 ok
- [ ] `/v1/mcp/status` 正常（MCP 开启时）
- [ ] 前端能打开并连上后端
- [ ] 填了 session（及必要时 Token）后能发出消息
- [ ] 能收到 Agent 回复（Markdown 和/或表单）
- [ ] （可选）需要查 API 的问题能看到工具调用，而不只是空话

全勾上 → [创建第一个 Skill](first-skill.md)。

---

## 出问题时看哪里

| 现象                 | 先查                                                              |
| -------------------- | ----------------------------------------------------------------- |
| 后端起不来 / 缺包    | [安装与部署](installation.md)；Python 是否 3.12+                  |
| Swagger / MCP 起不来 | URL 是否可访问；临时 `mcp.enable: false` 可只测对话（无法调 API） |
| 前端空白或代理失败   | 后端是否在 8010；Vite 是否在跑                                    |
| 提示要填业务 Token   | 补 Token / `X-MCP-Token`（无鉴权也可用 `demo` 占位）              |
| 有回复但不调 API     | Swagger 是否配上；问题是否需要工具；看 `logs/debug.log`           |
| LLM 超时 / 鉴权失败  | `llm.api_key` / `base_url` / `model` 是否与网关一致               |

结构化日志：仓库下 `logs/debug.log`（由 `logging.agent_log` 控制）。

---

## 刻意先不做的事

本页**不**覆盖：事件 Webhook、企微、长期记忆、RAG、A2A。主路径跑通后再看 [进阶功能](../advanced/README.md)。
