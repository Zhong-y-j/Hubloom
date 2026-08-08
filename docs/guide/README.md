# 入门指南

本部分目标很简单：知道 Hubloom 是什么、本地跑通「对话 → 调 API」、写出第一个 Skill。

不要求先懂 MCP 等协议——那是 [核心概念](../core-concepts/README.md) 的事。事件、企微等先进阶能力，等主路径跑通后再看 [进阶功能](../advanced/README.md)。

---

## 本章路径

建议按这个顺序读，安装章不必提前通读：

1. [Hubloom 是什么](what-is-hubloom.md) — 定位与边界（约 5 分钟）
2. [5 分钟快速上手](quick-start.md) — 跑通第一条对话并调到真实 API（约 10～15 分钟）
3. [创建第一个 Skill](first-skill.md) — 理解扩展点在哪（约 15 分钟）

卡住了再翻 [安装与部署](installation.md)。先跑起来，比先读完所有文档再动手要快。

---

## 开始之前

你只需要准备：

- 会改 YAML 配置即可（类似改 `application.yml`；不要求精通 Python）
- 一个可用的 **LLM API Key**（OpenAI 兼容接口即可，如 DeepSeek）
- **Redis**（必填）
- 一个 **Swagger / OpenAPI** 地址（自家业务 API 最好；没有时可先用公开样例练手）
- Node.js（仅跑演示前端时需要）

没有自家 Swagger 时，可先走通链路，再换成你的业务文档。

---

## 学完这一部分

你会：

- 搞清 Hubloom 的定位与边界
- 本地跑起 Serve 与演示对话页
- 用自然语言调到现有（或演示用）业务 API
- 知道 Skill 是什么、怎么写一个最简单的
