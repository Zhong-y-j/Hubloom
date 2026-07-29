# MCP Adapter

## MCP 协议介绍

大模型本身只会「说话」：推理、总结、建议都可以，但不会直接去查你们系统里的订单、改柜子状态、调企业内部 HTTP。若要让 Agent **真正办事**，就必须给它一条能调用外部能力的通道——业界常见做法是 function calling / tools：宿主把一批「工具」的名字、说明、参数 schema 交给模型，模型决定何时调用，宿主再去执行真实逻辑。

**MCP（Model Context Protocol）** 把这件事做成了**开放协议**，而不是绑死在某一家模型厂商的私有格式上。可以粗理解为：模型侧用统一方式**发现工具、调用工具**；服务侧把真实能力（调 REST、读资源等）暴露成标准的 tools。通信可以走本地子进程的 stdio，也可以走网络上的 HTTP（Streamable HTTP 等）。工具实现不必塞进 Agent 进程里，可以独立部署、独立扩容。

和「在应用代码里手写一堆 function calling」相比，协议化有几层实际好处：工具描述与调用约定更稳定，换模型或换宿主时不必重写一整套对接；工具可以放到独立进程或独立服务里，失败隔离、权限边界更清晰；同一套 MCP Server 也可以被别的兼容客户端复用，不只服务某一个聊天应用。

对 Hubloom 这种企业 Agent 平台来说，MCP 最对口的场景是：**你们已经有（或即将有）REST API，并有 OpenAPI / Swagger 契约**。不必把业务逻辑搬进 Hubloom 核心，也不必为每个接口手写一个 Python Tool 类——用契约生成可调用的 MCP 工具，再让 Agent 按协议去调。业务仍在原有 HTTP 服务里，鉴权仍是原来的 Bearer / JWT；Hubloom 负责编排与「怎么发现、怎么调用」。

读完这一节，你应能用自己的话说明：MCP 解决什么问题、和「纯聊天模型」差在哪、为什么企业场景特别适合「契约 → 工具」。下一节落到 Hubloom 里这条链具体起什么作用；再下一节讲为什么建成现在这样。协议官网与规范细节见 [MCP 协议（概念篇）](../core-concepts/mcp-protocol.md)；按配置接入见 [接入 Swagger](../usage/import-swagger.md)。

---

## Hubloom 中 MCP 起什么作用

Hubloom 的 Agent 要「办企业的事」，核心依赖就是：**把已有业务 API 变成 Agent 用得上的工具**。MCP Adapter（`src/mcp_adapter`）就是这条链路的实现层。

一句话：

> **配置 Swagger → 生成 / 连接 MCP 工具 → Agent 经元工具调用 → 带用户鉴权打到企业 HTTP（或连线上已有 MCP）。**

可以分几层看职责，避免和别的模块搅在一起。

企业 API 仍然是真相源：真正的业务规则、数据、权限都在那边。OpenAPI / Swagger 是契约：告诉系统有哪些接口、参数长什么样。MCP 后端（本地 stdio worker，或独立打成的 HTTP MCP 容器）把契约变成可调用的 tools，执行时再发真实 HTTP。Agent 面前默认不塞上百个接口名，而是两个元工具——`list_api` 按分组发现，`call_api` 真正调用——system prompt 里再挂一份「API 分组」名片，引导先选域再查详情。Skill 不替代 MCP：它约束「该怎么调、禁止什么」，真正打业务仍走工具通道。

所以 MCP 在 Hubloom 里扮演的是 **「业务能力插头」**：对话、企微、Events 换的是入口，后面办事往往还是同一批 API。换业务域，优先换 `swagger_url`、下游 Base、以及用户会话里的 Token，而不是重写 Runtime。Runtime 启动且 `mcp.enable=true` 时，会拉 catalog、连上 MCP 客户端、挂上元工具；进程退出时要关掉客户端，避免 stdio 子进程残留。

除了「自己用 Swagger 转出来的 MCP」，Adapter 也支持 **连接已经按 MCP 协议提供的线上工具服务**（HTTP URL）。企业主路与线上远端可以并存：主路继续服务你们的 OpenAPI；`remotes` 挂额外能力。当前 **HubloomRuntime 主路径仍是本地 stdio + 单一 swagger**；HTTP 独立部署、多路连接的能力在 Adapter 与配置里已具备，联调脚本可先用，挂进 Runtime 是后续装配。

和 Tools 模块的边界也要分清：Tools 管「Agent 工具面怎么挂、怎么跑、白名单与重试」；MCP Adapter 管「工具从哪来、怎么连上 Server、鉴权如何透传到下游」。模型调用的是 `list_api` / `call_api` 这两个 Tool；它们背后转发到 MCP 客户端。

读完上面，你应能说清：MCP 在 Hubloom 里接通的是什么、元工具为什么存在、和 Skill / Runtime / 入口模块各管哪一段。下一节讲设计取舍。

---

## 设计思路

介绍里说的是「要解决什么」。这一节说的是：**为什么建成现在这样，而不是另一种样子**。

### 1. 契约驱动，而不是手写每个 Tool

企业接口往往几十上百个。若为每个 operation 写一个 `BaseTool` 子类，契约一变就要改代码、发版，还容易和真实 Swagger 漂移。

因此选择：**OpenAPI 进、工具出**。`spec` 负责拉规范、规范化；`server` 用 FastMCP.from_openapi 生成全量工具；`gateway/catalog` 从同一份契约抽出 tag → 工具名，给 prompt 名片和 `list_api` 校验用。业务逻辑不搬进 Hubloom；换域主要换契约与 Token。

### 2. 模型面前两个元工具，背后仍是全量 MCP

若把全量 tools 一次性塞进模型的 tools 列表，上下文又长又吵，改契约还要整表重灌。若按 tag 起很多个 MCP 子进程，运维和连接数又会爆。

取舍是折中的：

- **背后**：一个全量 OpenAPI MCP（不按 tag 拆多个 Server）。
- **模型面前**：只有 `list_api(tag)` / `call_api(tag, tool_name, arguments)`。
- **prompt**：注入「API 分组」目录，先选分组再发现再调用。

直觉：目录在 prompt 里，详情按需 `list_api`，办事必须 `call_api`。

### 3. 传输双模式：本地 stdio 保留，生产可独立 HTTP

本地开发最省事的是：Runtime 拉起一个 worker 子进程，stdio 连上——无需另起容器，联调快。但单管道 stdio 天然难扛多 Agent 并发：多请求挤在同一条读写上，慢且有协议风险。示例站曾用全局锁串行保护，根因往往就在这里，而不在业务重复。

因此 Adapter 做成双模式，而不是二选一废弃：

- **stdio**：现有路径，`connect_full_mcp` / Runtime 默认仍走这条。
- **http**：同一套 `build_backend_mcp`，用 `worker --http` 独立监听（默认可无状态会话，利于并发）；也可打成单独容器（见包内 Dockerfile）。Hubloom 用 `connect_http_mcp` 当客户端去连。

客户端对外仍是同一个 `MCPToolClient` 接口（`list_tools` / `execute_tool` / `close`），上层元工具不必为传输分叉两套代码。

### 4. 多路 MCP：企业主路与线上工具分开挂

线上已有的 MCP（搜索、内部运维工具等）和「Swagger 转出来的企业 API」语义不同，不宜硬塞进同一套 OpenAPI tag / `call_api` 模型。

设计上用 **多路 endpoint + 注册表**：

- 每一路有稳定 `id`（如 `primary`、`search`）。
- stdio 路吃 `swagger_url`；http 路吃 `url`（及可选 headers）。
- `MultiMcpRegistry` 按 id 持有多个客户端；列出时可加 `{id}__` 前缀，避免工具名冲突。

配置层（`mcp.transport` / `url` / `remotes` / `serve`）已能解析；Runtime 尚未把 remotes 挂进 Agent 工具面——先保证 Adapter 与联调脚本一步到位，再改装配，避免半截 Runtime。

### 5. 鉴权按请求透传，不把用户 Token 写进配置文件

企业 API 通常要带当前用户的 Bearer。若把 Token 写在 yaml 或子进程环境里当「全局密钥」，多用户会串权，密钥也难轮转。

路径是：对话 / 企微换票得到的 Token 进请求上下文 → `call_api` 调 MCP 时放进协议 `_meta` → Server 中间件取出 → 下游 HTTP 的 `Authorization`。配置里的 `auth_scheme` / 可选服务级 `token` 只作前缀约定或联调回退；正式业务鉴权应走 `session(token=...)`。独立 HTTP 部署时，同一套透传语义要对齐，避免「stdio 能带票、HTTP 丢票」。

### 6. 包内分层清晰，Runtime 只依赖装配入口

`mcp_adapter` 刻意拆开，避免一个大文件既拉 Swagger 又跑 HTTP 又管 Agent：

| 部分 | 管什么 |
| --- | --- |
| `spec` / `gateway` | 契约加载、catalog、分组名片 |
| `server` | OpenAPI → FastMCP；stdio 或 HTTP 进程入口 |
| `client` | 连 Server、list/call、多路注册表 |
| `auth` | `_meta` ↔ 下游 Authorization |
| `discovery` | `load_agent_mcp_bindings`、`connect_*` 装配 |

Runtime 主要认 `load_agent_mcp_bindings`（catalog + 客户端 + 元工具）。测 MCP 可以不经 Agent：起 HTTP 服务、列工具——见 `tests/test_mcp_serve_swagger.py` 与 `tests/test_mcp_list_tools.py`。

主链路可以记成：

```text
swagger_url / 远端 url
        │
        ▼
  MCP Server（stdio 子进程 或 HTTP 容器）
        │
        ▼
  MCPToolClient（同接口）
        │
        ├── list_api / call_api（企业主路，Runtime 已挂）
        └── MultiMcpRegistry（多路；配置已有，Runtime 待接）
                │
                ▼
        下游业务 HTTP / 线上 MCP 工具
```

一句话对照：

| 若做成… | 我们选择… | 主要理由 |
| --- | --- | --- |
| 每个 API 一个手写 Tool | OpenAPI → 全量 MCP + 两元工具 | 契约驱动、上下文可控 |
| 只保留 stdio | stdio + 可独立 HTTP | 本地简单、生产可扩并发 |
| 远端工具塞进 call_api 的 tag | 多路 registry + 前缀名 | 语义不混、防撞名 |
| Token 写死在配置 | 请求级 `_meta` 透传 | 多用户不串权 |

---

## 相关章节

- 概念：[MCP 协议](../core-concepts/mcp-protocol.md)
- 上一篇：[Tools](tools.md)
- 下一篇：[Skill](skill.md)
- 使用：[接入 Swagger](../usage/import-swagger.md)
- 代码：`src/mcp_adapter/`（`discovery` / `client` / `server` / `gateway` / `auth`）
