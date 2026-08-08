# Skill

**Skill** 是给 Agent 的领域规程（Markdown）：说明某类事该怎么做、先做什么、禁止什么。

它不是业务代码，也不会替你的后端落库。

> **Swagger / MCP 回答「能调什么」；Skill 回答「该怎么调、注意什么」。**

可以这样理解分工：

- **Swagger / MCP** — 有哪些接口、怎么发真实 HTTP
- **Skill** — 办事顺序、确认点、禁区等业务规矩
- **企业后端** — 真正落库、算账、鉴权
- **Agent** — 决定何时读 Skill、何时调工具

Runtime 加载 `skills/*/SKILL.md` 后，通常只把 **name + description** 当作名片放进提示；意图对得上时，再 `read_skill` 读正文，然后仍靠 MCP 调真实 API。Runtime **不会**执行 Skill 里的脚本。

写 Skill 时记住这几条就够：

- 目录：`skills/<id>/SKILL.md`（只扫一层目录）
- `description` 要具体，否则模型很难决定何时读取
- 正文写清：何时用 → 步骤 → 红线；短比长好
- 改完后需重启 Serve 才生效（当前无热加载）

事件用的 `skills/events/` 是另一套约定，见 [进阶功能](../advanced/README.md)。

可以把它想成：**MCP 是工具箱；Skill 是操作规程；Agent 按规程从工具箱里取用。**

动手写一个见 [创建第一个 Skill](../guide/first-skill.md)；更完整的写法见 [编写 Skill](../usage/write-skill.md)；加载与实现细节见 [Skill 模块导读](../modules/skill.md)。
