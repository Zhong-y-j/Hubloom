# Hubloom Skills

本目录存放 **手写** Agent Skill 说明。

## 当前约定

- 公共平台 Skill：[`hubloom/SKILL.md`](hubloom/SKILL.md)
- **不**按 OpenAPI tag / 业务域自动生成 Skill
- **未**接入 `HubloomAgent` / Thought（发现与工具仍靠 prompt 中的 API catalog + 元工具）

## 布局

```
skills/
  hubloom/
    SKILL.md     # 平台用法（已纳入版本库）
  README.md
```

日后若要接入运行时（渐进披露、定时任务剧本等），再单独改 runtime；本目录先作为文档存放处。
