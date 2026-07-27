# Memory

> 状态：大纲（待编写正文）

## 本章要讲清

- 默认：会话历史（按 `session_id`）存在哪、谁读写
- 可选：长期记忆 / handler / store / worker 的分层
- 与 Agent 回合、工具面的挂接方式

## 代码锚点

- `src/memory/`（`manager.py`、`factory.py`、`handlers/`、`store/` 等）
- Runtime 中 `_make_memory` / 配置开关

## 相关章节

- 进阶：[会话与记忆](../advanced/memory.md)
- 总览：[模块导读](README.md)
- 下一篇：[Retrieval](retrieval.md)
