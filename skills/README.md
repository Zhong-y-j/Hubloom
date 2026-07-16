# Hubloom Skills

本目录存放 **手写** Agent Skill 说明（`*/SKILL.md`）。运行时由 `skills.loader` 扫描，在 `HubloomAgent.create` → `build_runtime_async` 时缓存为 `CortexRuntime.skills_prompt`，再拼进 Chat / Thought 的 system prompt。

## 配置

见 `config/env.example.yaml`：

| 键 | 含义 |
|----|------|
| `skills_dir` | Skills 根目录（相对仓库根，默认 `skills`） |
| `skills_exclude` | 目录名黑名单；**空列表 = 注入全部** |

## 注入位置与顺序

| 路径 | 函数 | 是否注入完整 Skills | 拼接顺序 |
|------|------|---------------------|----------|
| Chat 快答 | `build_chat_system_prompt` | **是** | 角色基座 → **Skills** → API 分组 → 工具简表 |
| Thought 研判 / 执行 | `build_deliberate_prompt` / `build_execute_prompt` | **否** | 阶段基座 → API 分组 → 工具简表（避免在思考区照抄 A2UI few-shot） |
| Thought 最终回复 | `build_respond_prompt` | **是** | 回复基座 → **Skills**（A2UI 输出约定仅在此） |

Assessor 路由与 `THOUGHT_CONTEXT_SYSTEM` **不**注入 Skills。

运行时另有兜底：思考流若仍出现 `---a2ui_JSON---`，会剥掉并尽量提升为最终 `event: a2ui`。

## 当前 Skill

| Skill | 路径 | 用途 |
|-------|------|------|
| Generative UI | [`a2ui/SKILL.md`](a2ui/SKILL.md) | Markdown vs A2UI、输出约定与 few-shot |

新增 Skill：在 `skills/<id>/` 下写 `SKILL.md`。不想注入时把 `<id>` 加进 `skills_exclude`。
