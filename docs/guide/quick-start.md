# 5 分钟快速上手

本章目标：在本机跑通一条 **「对话 → 调真实 API」** 主路径。

跟着做一般十几分钟就能跑通；若要第一次对接自家 Swagger 和鉴权，多留一点时间排查即可。

装依赖或环境报错 → [安装与部署](installation.md)。  
还不清楚产品定位 → [Hubloom 是什么](what-is-hubloom.md)。

---

## 完成后你会有什么

- Serve 在 `http://127.0.0.1:8765` 健康检查通过
- 演示对话页能打开（默认 `http://127.0.0.1:5173`）
- 发一句话能收到 Markdown 回复；MCP 开启时能调到 OpenAPI 里的接口

---

## 开始之前

准备好：

- Python 3.12+（推荐 [uv](https://github.com/astral-sh/uv)）
- **Redis**（必填；本机已有 `6379` 即可，也可用仓库 `./start.sh infra` 只起基础设施）
- LLM API Key（OpenAI 兼容接口，如 DeepSeek）
- OpenAPI / Swagger 地址（自家最好；没有时可用公开 Petstore 练手）
- Node.js（仅跑演示前端时需要）

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
redis:
  url: redis://127.0.0.1:6379/0

llm:
  api_key: sk-你的密钥
  model: 你的模型名 # 以网关实际名为准
  base_url: https://api.xxx.com # OpenAI 兼容 Base URL

mcp:
  enable: true
  # 练手：公开 Petstore；接业务时改成你的 Swagger JSON 地址
  swagger_url: https://petstore.swagger.io/v2/swagger.json
  auth_scheme: Bearer
```

注意：

- **不要**把业务用户 Token 写进 `env.yaml`；在对话页或请求头传入。
- `config/env.yaml` 含密钥，仓库已 ignore，**勿提交**。

细讲：[配置 LLM](../usage/configure-llm.md) · [接入 Swagger](../usage/import-swagger.md)。

---

## 步骤 3：启动 Hubloom Serve

先确认 Redis 可用（本机已有服务，或 `./start.sh infra`）。

```bash
PYTHONPATH=src uv run python main.py
```

默认监听 `http://0.0.0.0:8765`（见配置 `http.port`）。

另开终端自检：

```bash
curl -s http://127.0.0.1:8765/health
# 期望含 "status":"ok" 一类字段

curl -s http://127.0.0.1:8765/v1/mcp/status
# MCP 开启且 Swagger 加载成功时，应看到就绪相关字段（而非报错）
```

可选：打开 http://127.0.0.1:8765/docs 查看 API。

---

## 步骤 4：启动演示前端

再开一个终端：

```bash
cd examples/chat/web
npm install
npm run dev
```

浏览器打开 Vite 提示的地址（默认 http://127.0.0.1:5173）。  
`/v1`、`/health` 会代理到 Serve（默认 `:8765`）。

在页面上：

- **Session** — 任意，如 `demo-session`（多轮靠它隔离；页面也可能自动生成）
- **业务 Token** — 有鉴权的业务 API 填真实 Bearer；Petstore 等公开接口可填占位如 `demo`
- 先看 Markdown 结论与可展开的工具过程即可

---

## 步骤 5：发第一句话

示例：

- Petstore：`列出可用的宠物相关接口` / `查一下宠物店里有哪些宠物`
- 自家 API：用你们业务里的真实说法，如「查询某某状态」

期望：能收到 Agent 回复；需要调 API 时，过程中能看到工具调用。

仅验后端可用：

```bash
curl -s http://127.0.0.1:8765/v1/chat \
  -H "Content-Type: application/json" \
  -H "X-Session-Id: demo-session" \
  -H "X-MCP-Token: demo" \
  -d '{"message":"你好，你能做什么？","stream":false,"wait_profile":"interactive"}'
```

查历史：

```bash
curl -s "http://127.0.0.1:8765/v1/chat/history?session_id=demo-session"
# 可选填回思考：&include_thought=true
```

---

## 验收一下

- `/health` 正常
- MCP 开启时 `/v1/mcp/status` 正常
- 前端能打开并连上后端
- 填了 session（及必要时 Token）后能发出消息
- 能收到 Agent 回复
- （可选）需要查 API 的问题能看到工具调用，而不只是空话

都过了 → [创建第一个 Skill](first-skill.md)。

---

## 出问题时看哪里

- **后端起不来 / 缺包** — [安装与部署](installation.md)；Python 是否 3.12+
- **Redis 连不上** — `redis.url` 是否正确；本机 Redis 是否在跑
- **Swagger / MCP 起不来** — URL 是否可访问；临时 `mcp.enable: false` 可只测对话（无法调 API）
- **前端空白或代理失败** — Serve 是否在 8765；Vite 是否在跑
- **提示要填业务 Token** — 补 Token / `X-MCP-Token`（无鉴权也可用 `demo` 占位）
- **有回复但不调 API** — Swagger 是否配上；问题是否需要工具；看 `logs/debug.log`
- **LLM 超时 / 鉴权失败** — `llm.api_key` / `base_url` / `model` 是否与网关一致

结构化日志：仓库下 `logs/debug.log`（由 `logging.agent_log` 控制）。

---

## 刻意先不做的事

本页**不**覆盖：事件 Webhook、企微、长期记忆、RAG、A2A。主路径跑通后再看 [进阶功能](../advanced/README.md)。
