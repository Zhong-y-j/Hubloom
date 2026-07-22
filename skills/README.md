# Hubloom Skills

Skill 用来固化**领域 Know-how / 办事规程**（何时读、怎么调业务、禁止什么），业务逻辑仍留在企业 API。  
本目录下的 `*/SKILL.md` 会被 Runtime 扫描；本文件（`README.md`）只给人看，**不会**注入模型。

## 当前能力（已实现）

| 能力       | 说明                                                                       |
| ---------- | -------------------------------------------------------------------------- |
| 扫描加载   | `load_skills` 读 `skills_dir/*/SKILL.md`（frontmatter + 正文）             |
| 名片注入   | system 里只放 **name + description**（见 Think 提示中的「可用 Skills」）   |
| 按需读正文 | 工具 **`read_skill(skill=目录id或name)`**；同一 Skill **每轮最多成功一次** |
| 排除列表   | 配置 `skills_exclude` 按**目录名**黑名单（如 `a2ui`）                      |

**没有**的能力：

- 没有 `call_skill` / 没有把 Skill 当可执行插件跑业务
- **暂无** `run_skill_script` 或沙箱执行 `scripts/*`（见下文「脚本」）

读完 Skill 正文后，仍靠 **`list_api` / `call_api`**（MCP）办实事，或交 Respond 说明 / 出 A2UI。

## 目录约定

```text
skills/
  README.md                 # 本说明（不注入 Agent）
  <skill-id>/
    SKILL.md                # 必填：YAML frontmatter + Markdown 正文
    scripts/                # 可选：附带脚本（当前 Runtime 不会自动执行）
```

- **目录名** = Skill **id**（`read_skill` 推荐用这个，如 `account-access`）
- frontmatter **name** 可与 id 不同；解析时 **id 优先，其次 name**
- 以 `.` 开头的目录会被忽略

## `SKILL.md` 格式

```markdown
---
name: my-skill
description: >
  一两句：什么场景该用。写进「可用 Skills」名片，务必具体，便于模型匹配。
---

# 标题

## 何时使用

...

## 步骤 / 规则 / 禁止项

...
```

- `description` 支持 `>` 多行；加载后会拼成一行名片文案
- 正文写清：触发条件、步骤、与 MCP 的配合、红线；需要交互时写清 Markdown / A2UI 建议
- **缺参时不要教模型编造参数**；与 Think 提示一致：缺必填则交 Respond 收集

## Agent 侧怎么用

1. 用户意图与某条 **description** 明显匹配 → `read_skill`
2. 按正文办事：该拒就拒、该 `list_api`/`call_api` 再调、该交 Respond 就停
3. 同一轮不要重复 `read_skill`；正文已在工具结果里时禁止再读
4. `read_skill` **只加载说明书**，不等于业务已执行

相关代码：`src/skill/load.py`、`src/tools/builtin/skill_tools.py`、`src/agent/prompts.py`、`src/runtime.py`。

## 如何添加一个 Skill

1. 新建 `skills/<skill-id>/SKILL.md`（frontmatter 必填 `name` / `description`）
2. 若需纳入 Git：在根目录 `.gitignore` 里为该目录加白名单（当前默认 `/skills/*` 忽略，仅白名单公共 Skill）
3. 重启 Runtime（或重新 `HubloomRuntime.from_config`），确认名片出现在 Think system 中
4. 用对话验证：相关意图会先 `read_skill`，再按正文行动

配置（见 `config/env.example.yaml`）：

```yaml
skills_dir: skills
skills_exclude: [] # 目录名黑名单；需要时如 [a2ui]
```

## 仓库里现有 Skill

| id                   | 作用                                                                 |
| -------------------- | -------------------------------------------------------------------- |
| `account-access`     | 禁止代办登录/改密/改资料；业务 401/403 引导侧栏 Token               |
| `select-before-act`  | 列表选型 / 关联绑定：先展示候选（默认前 10）再动手；删除须二次确认 |

## 关于附带脚本（暂缓）

**结论（当前）：不实现 Skill 脚本执行器。**

原因简要：

- Hubloom 主路径是 OpenAPI → MCP → `call_api`；领域规程用 Markdown Skill + `read_skill` 已够用
- 无沙箱时「在 Skill 里写 `python scripts/...`」模型无法真正执行，易误导

在此之前：

- Skill **以正文规程为主**（对标 `account-access`）
- `scripts/` 可作草稿或人工本地跑，**不要**在 SKILL.md 里写成 Agent 必经步骤

若以后要做脚本能力，应另开设计：路径限制在 `skills/<id>/scripts/`、超时/输出上限、禁止联网与任意 shell，并改提示词与本 README。

## 写 Skill 时注意

- **做**：固化禁区、多步顺序、缺参策略、与现有 MCP 工具如何配合
- **不做**：把 CRUD 业务搬进 Skill；在对话里收集密码；依赖尚未存在的工具（如脚本执行器）
- A2UI 是呈现通道，不是业务 Skill；若仓库有参考用 `a2ui` 目录，可按需加入 `skills_exclude`
