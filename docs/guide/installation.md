# 安装与部署

本章是**备查页**：按 [快速上手](quick-start.md) 卡住时再来查。以**本地开发**为主；生产镜像见文末简要说明。

配置项全表见 [配置项说明](../reference/configuration.md)（正文完善中时可先对照 `config/env.example.yaml`）。

---

## 环境要求

| 组件                                                | 要求                            | 用途                |
| --------------------------------------------------- | ------------------------------- | ------------------- |
| Python                                              | **3.12+**                       | Runtime 与示例后端  |
| [uv](https://github.com/astral-sh/uv)（推荐）或 pip | —                               | 安装 Python 依赖    |
| Node.js + npm                                       | 跑示例前端时需要                | `examples/chat/web` |
| 网络                                                | 能访问 LLM 网关与 `swagger_url` | 对话与 MCP 拉规格   |

不要求精通 Python；会改 YAML、会跑命令即可。

---

## 获取代码

```bash
git clone https://github.com/Zhong-y-j/Hubloom.git
cd Hubloom
```

若使用 Gitee 等镜像，换成对应远程地址。

---

## 安装 Python 依赖

在仓库根目录：

```bash
uv sync
```

或：

```bash
pip install -r requirements.txt
```

验证：

```bash
uv run python -c "import fastapi; print('ok')"
# 或：python -c "import fastapi; print('ok')"
```

---

## 配置文件

```bash
cp config/env.example.yaml config/env.yaml
```

| 文件                      | 说明                                             |
| ------------------------- | ------------------------------------------------ |
| `config/env.example.yaml` | 可提交的模板                                     |
| `config/env.yaml`         | 本地真实配置（含密钥，**已 gitignore，勿提交**） |

加载方式：启动时读 `config/env.yaml`；也可用环境变量 `HUBLOOM_CONFIG` 指向其它路径。

**最小必填（跑通对话 + MCP）：**

- `llm.api_key` / `llm.model` / `llm.base_url`
- `mcp.enable: true` 时的 `mcp.swagger_url`

**建议首次保持关闭：**

- `memory.enable_long_term: false`
- `rag.enable: false`
- `events.enable` / `im.wecom.enable` 先不要开

业务用户 Token **不要**写进 yaml，在前端或 `X-MCP-Token` 传入。

---

## 目录速览（与安装相关）

```text
Hubloom/
├── config/           # env.example.yaml → env.yaml
├── main.py           # 启动示例后端入口
├── src/              # Runtime 与适配层（PYTHONPATH 需包含）
├── examples/chat/    # 示例站后端路由 + web 前端
├── skills/           # Skill 规程
├── data/             # 默认会话库等（运行后生成）
└── logs/             # debug.log 等
```

---

## 本地进程与端口

| 进程 | 默认地址                | 启动                                                 |
| ---- | ----------------------- | ---------------------------------------------------- |
| 后端 | `http://127.0.0.1:8010` | `PYTHONPATH=src:. uv run python main.py`             |
| 前端 | `http://127.0.0.1:5173` | `cd examples/chat/web && npm install && npm run dev` |

前端把 `/v1`、`/health` 代理到 `8010`。

常用环境变量：

| 变量                | 含义                                 |
| ------------------- | ------------------------------------ |
| `CORTEX_API_HOST`   | 后端绑定地址（默认 `0.0.0.0`）       |
| `CORTEX_API_PORT`   | 后端端口（默认 `8010`）              |
| `CORTEX_API_RELOAD` | 设为 `1`/`true` 可开热重载（若支持） |
| `HUBLOOM_CONFIG`    | 配置文件绝对/相对路径                |

健康检查：

```bash
curl -s http://127.0.0.1:8010/health
```

---

## 常见安装问题

| 现象                                         | 处理                                              |
| -------------------------------------------- | ------------------------------------------------- |
| `python` 版本过低                            | 安装/切换到 3.12+（`python3 --version`）          |
| `ModuleNotFoundError` / 找不到 `im`、`agent` | 确认在仓库根启动，且带 `PYTHONPATH=src:.`         |
| `uv: command not found`                      | 安装 uv，或改用 `pip install -r requirements.txt` |
| `npm` / 前端起不来                           | 安装 Node.js LTS；删掉 `node_modules` 后重装      |
| 创建 `env.yaml` 后仍读旧配置                 | 检查是否改错文件；是否设置了别的 `HUBLOOM_CONFIG` |
| 拉不到 `swagger_url`                         | 本机网络/代理；先在浏览器打开该 URL 试是否 JSON   |
| 端口被占用                                   | 改 `CORTEX_API_PORT`，或关掉占用 8010/5173 的进程 |
| 权限 / 写不了 `data/`、`logs/`               | 确认仓库目录可写                                  |

仍失败时看 `logs/debug.log`，并把启动终端里的完整报错留着对照。

---

## Docker（简要）

仓库含 `Dockerfile`，偏向把示例 API 打成镜像；**默认暴露逻辑以镜像内 `PORT`（常见 8000）为准**，与本地开发默认 `8010` 可能不同。

本地第一次上手**建议先不用 Docker**，按上文两个终端跑通。需要容器化时再对照 `Dockerfile` / 部署环境设置 `PORT`、挂载 `config` 与 `data`，并保证容器能访问 LLM 与 Swagger 地址。
