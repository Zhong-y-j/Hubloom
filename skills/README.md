# Hubloom Skills

本目录存放 **手写** Agent Skill（`*/SKILL.md` + 可选 `references/`、`scripts/`）。  
运行时由 `skills.loader` 扫描，在 `build_runtime_async` 时缓存为 `CortexRuntime.skills_prompt`。

## 配置

见 `config/env.example.yaml`：

| 键 | 含义 |
|----|------|
| `skills_dir` | Skills 根目录（相对仓库根，默认 `skills`） |
| `skills_exclude` | 目录名黑名单；默认含 `a2ui` |

## 注入位置

| 路径 | 是否注入 Skills |
|------|-----------------|
| Chat 快答 | **是**（其它业务 Skill；Chat 本身禁止 A2UI） |
| Thought 研判 / 执行 | **否** |
| Thought 最终回复 | **是**（其它业务 Skill） |

**A2UI 最终回复**由官网 ``A2uiSchemaManager`` 生成（``agents/a2ui_prompt.py``，与 ``a2ui/agent.py`` 同源），**不再依赖** `skills/a2ui` 注入。  
`skills/a2ui/` 目录仍保留作参考模板，默认在 `skills_exclude` 中。

## Skill 目录约定

```text
skills/<id>/
├── SKILL.md
├── references/   # 可选；templates 等可被 loader 注入（examples/ 除外）
└── scripts/      # 可选；不注入
```

新增业务 Skill：在 `skills/<id>/` 写 `SKILL.md`。不想注入时把 `<id>` 加进 `skills_exclude`。
