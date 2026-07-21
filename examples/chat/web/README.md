# Vue 前端（Agent 对话 + A2UI 场景实验室）

## 启动

仓库根目录开两个终端：

```bash
# 1) 后端（默认 http://127.0.0.1:8010）
PYTHONPATH=src:. uv run python main.py

# 2) 前端
cd examples/chat/web
npm install
npm run dev
```

浏览器打开 Vite 提示的地址（默认 `http://127.0.0.1:5173`）。  
Vite 将 `/v1`、`/health` 代理到 `http://127.0.0.1:8010`。

## 后端接口

| 方法 | 路径 | 说明 |
|------|------|------|
| `POST` | `/v1/chat` | 对话（默认 SSE） |
| `GET` | `/v1/chat/history?session_id=` | 会话历史（含 thought / tools / a2ui） |
| `GET` | `/v1/mcp/status` | MCP 就绪状态 |
| `GET` | `/health` | 健康检查 |

请求头：`X-Session-Id`、`X-MCP-Token` 或 `Authorization: Bearer …`。

样式：`src/styles.css`（含 `--a2ui-*` 与 chat 布局）。
