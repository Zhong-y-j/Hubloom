# Runtime

> 状态：大纲（待编写正文）

## 本章要讲清

- `HubloomRuntime`：进程级装配（LLM、MCP、Think/Respond system、默认呈现模式）
- `HubloomConfig` / `config/env.yaml` 如何进入 Runtime
- `context`：单轮 `bearer_token`、session 等请求上下文
- `from_config` → `run_stream` 的主路径

## 代码锚点

- `src/runtime.py`
- `src/config.py`
- `src/context.py`
- `main.py`（示例入口）

## 相关章节

- 总览：[模块导读](README.md)
- 下一篇：[Agent](agent.md)
- 使用：[嵌入 Runtime](../usage/embed-runtime.md)
