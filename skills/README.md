# Hubloom Skills

本目录用「文件夹 + SKILL.md」存放 Agent Skill。

## 自动生成（第一版）

`HubloomAgent.create` 在 **MCP catalog 加载成功后**：

1. 若本目录（或 `config.skills_dir`）下 **已有任意** `*/SKILL.md` → **整次跳过**生成  
2. 若一个都没有 → 按 OpenAPI **每个 tag 生成一个** `skills/<tag>/SKILL.md`（可走 LLM，失败用规则模板）

**当前仓库若保留示例 [`hotel-booking/`](hotel-booking/)，会阻止自动生成。**  
想从 Swagger 生成时：先移走/改名该示例，或把 `skills_dir` 指到空目录。

本步 **只写 `SKILL.md`**，不自动创建 `references/` / `scripts/` / `assets/`。  
运行时渐进披露 / Thought 注入仍未接通。

## 布局

```
skills/
  <skill-id>/
    SKILL.md              # 必填
    references/           # 可选（手写或后续再生成）
    scripts/
    assets/
```

## 配置

```yaml
skills_dir: skills   # 相对仓库根；省略则默认 skills
```
