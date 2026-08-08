# Runtime

**Runtime（`HubloomRuntime`）** 是可嵌入的办事内核：在进程里把配置装配成一套可运行的 Agent 能力，再按会话把每一轮跑起来。

一句话：

> **装配一次 → 按 `session_id` 执行 `run_stream` / `resume_stream` → 退出时释放资源。**

它主要装配这些东西：

- **LLM** — 对话与编排用的模型客户端
- **MCP（可选）** — 按 Swagger 拉起的工具通道
- **Skill** — 扫描 `skills/`，生成可注入的规程名片（及可选 Playbook）
- **会话能力** — 历史读写、默认 Wait Profile 等
- **工具面** — 把 MCP 元工具、`read_skill` 等挂到 Agent 能调用的位置

装配完成后，宿主（Hubloom Serve，或你自己的应用）每次用户开口，只要调用 Runtime 的 `run_stream`（挂起后续跑用 `resume_stream`）。Runtime 会按会话准备上下文，再交给 **Agent** 做决策与工具循环；进程退出时再 `aclose`，关掉 MCP 等资源。

可以把它想成：**Serve / 自有宿主管入口，Runtime 管「把 Agent 跑起来」，Agent 管「这一步怎么决策」。**

Runtime **不管**前端怎么画、BFF 怎么鉴权，也不代替 Agent 逐步决策。

细讲（生命周期、边界、代码锚点）见 [Runtime 模块导读](../modules/runtime.md)；嵌入方式见 [嵌入 Runtime](../usage/embed-runtime.md)。
