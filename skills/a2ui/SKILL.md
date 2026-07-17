---
name: a2ui
description: >-
  【参考归档】A2UI 模式与模板；运行时默认 skills_exclude 含 a2ui。
  Thought 最终回复的 A2UI 约定已内置在 agents/adp/thought.py 的 respond prompt。
priority: low
---

# A2UI（参考归档）

> Hubloom 现网：**Thought respond 内置 A2UI 输出约定**（`<a2ui-json>`），不再依赖本 Skill 注入。  
> 本目录保留模板与模式说明，供对照与二次开发。若要重新注入，从 `skills_exclude` 去掉 `a2ui`。

面向 **Hubloom 对话 Agent** 的 Generative UI 参考材料。  
协议：**v0.9.1**；Catalog：Basic。

详见 `references/`（patterns、templates）。运行时最终回复请遵循 Thought `build_respond_prompt` 中的内置规则。
