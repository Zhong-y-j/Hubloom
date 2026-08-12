# Hubloom

**快速把企业 API 编成私有化 Agent，策略约束下自动执行业务操作。**

接上现有的 Swagger/OpenAPI，用自然语言在真实业务 API 上办事。业务逻辑仍在你的系统里；Hubloom 是可私有化的 **Agent 服务**，推荐经 **企业后端（BFF）** 转发接入（鉴权 / 限流放在你这边）。流程用 **Skill** 约束，也可经 **Events** 事件驱动触发。

完整说明见 [在线文档](https://zhong-y-j.github.io/Hubloom/)。

---

## 快速开始

**环境：** Python 3.12+ · [uv](https://github.com/astral-sh/uv)（推荐）· **Redis**（必填）· Node.js（仅演示前端）

```bash
uv sync
cp config/env.example.yaml config/env.yaml
```

在 `config/env.yaml` 至少填写 `llm.*`、`redis.url`；启用 MCP 时再配 `mcp.swagger_url` / `base_url`。  
业务 Bearer 由请求传入，不要写进配置文件。

```bash
# 产品 API（默认 :8765）
PYTHONPATH=src uv run python main.py

# 演示前端（另开终端）
cd examples/chat/web && npm install && npm run dev
```

- 对话页：http://127.0.0.1:5173/
- API 文档：http://127.0.0.1:8765/docs

```bash
curl -s http://127.0.0.1:8765/v1/chat \
  -H "Content-Type: application/json" \
  -H "X-Session-Id: demo-session" \
  -H "X-MCP-Token: your-business-token" \
  -d '{"message":"你好，你能做什么？","stream":false,"wait_profile":"interactive"}'
```

---


## 许可证

[Apache License 2.0](LICENSE)
