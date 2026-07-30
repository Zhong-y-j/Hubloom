# Hubloom 示例对话前端

纯前端，对接仓库内 **Hubloom Serve**（无 A2UI / AG-UI）。

## 启动

```bash
# 终端 1：产品 API（默认 http://127.0.0.1:8765，见 config http.port）
PYTHONPATH=src .venv/bin/python -m server serve --config config/env.yaml
# 或：PYTHONPATH=src .venv/bin/python main.py

# 终端 2：本前端
cd examples/chat/web
npm install
npm run dev
```

浏览器打开 Vite 提示的地址（默认 `http://127.0.0.1:5173`）。  
`/v1`、`/health` 代理到 Serve；可用环境变量覆盖：

```bash
HUBLOOM_SERVE_URL=http://127.0.0.1:8765 npm run dev
```

## 行为说明

- `POST /v1/chat`：新一轮（`wait_profile=interactive`）
- 收到 `awaiting_user` 后，下一条输入走 `POST /v1/chat/resume`
- Markdown 渲染回复；工具调用可在侧栏开关显示
