# Skill

## Skill 是什么？

在 Agent 语境里，**Skill（技能）**是一份可复用的「专项能力包」：把某类任务需要的**做法、流程、注意点**写成文件，让通用 Agent 在遇到相关任务时，能按专家方式做事，而不是每次靠临时提示词从头教。

业界常见说法（如 Agent Skills / `SKILL.md` 一类约定）里，一个 Skill 通常是：

- 一个**文件夹**
- 里面至少有一份 **`SKILL.md`**
- 可选再带脚本、参考资料、模板等资源

`SKILL.md` 一般分成两层信息：

| 部分                                              | 内容                         | 作用                              |
| ------------------------------------------------- | ---------------------------- | --------------------------------- |
| **元数据**（文首 YAML，如 `name`、`description`） | 技能叫什么、**什么时候该用** | 给 Agent 做「目录／索引」，体积小 |
| **正文**（后面的 Markdown）                       | 具体步骤、规范、禁区、示例   | 真正办事时才需要读的细则          |

设计上的关键点是**按需展开（progressive disclosure）**：

1. 平时只让 Agent 知道「有哪些 Skill、各自适用什么场景」（元数据）；
2. 当前用户任务对得上某条描述时，再加载该 Skill 的正文；
3. 若正文里还引用了别的文件，再按需要去读——而不是一上来把所有手册塞进上下文。

可以把它想成给新同事的**入职材料**：先发一页岗位说明（何时找谁），真正上手某类活时再翻完整操作手册；手册本身通常**不是**替代业务系统的按钮，而是告诉人（或 Agent）**按什么规矩去做**。

和「工具／API」的差别也宜先分清：

|                | 大致回答                                 |
| -------------- | ---------------------------------------- |
| **工具 / API** | 能调用哪些能力、参数是什么               |
| **Skill**      | 遇到这类事该怎么做、注意什么、哪些不能做 |

---

## Skill 长什么样？

### 目录结构

一个 Skill 就是一个文件夹。最小只要有一份 `SKILL.md`；需要时再加附属资源：

```text
my-skill/                 # 文件夹名 = 技能 id（建议小写、短横线）
  SKILL.md                # 必填：元数据 + 正文
  scripts/                # 可选：脚本（是否执行取决于具体产品）
  references/             # 可选：补充说明、长文档
  assets/                 # 可选：模板、样例等
```

常见约定：

- **一层一个 Skill**：不要写成 `skills/foo/bar/SKILL.md` 还指望被自动扫成独立技能（多数实现只认「技能根目录下的 `SKILL.md`」）。
- **文件夹名**用来标识这个技能（调用、排除名单时常用它）。
- 以 `.` 开头的目录通常忽略；给人看的总说明（如 `README.md`）一般**不会**当成 Skill 正文注入模型。

多个技能并排放在同一父目录下，例如：

```text
skills/
  README.md                 # 给人看，通常不注入模型
  account-access/
    SKILL.md
  select-before-act/
    SKILL.md
```

### `SKILL.md` 写什么？

文件固定两段：**文首 YAML（元数据）** + **后面的 Markdown（正文）**。

```markdown
---
name: account-access
description: >
  一句话说明：这个技能做什么，以及什么时候该用它。
  description 越清楚，Agent 越容易判断「当前任务要不要读这份」。
---

# 标题（正文开始）

这里写具体做法：步骤、检查清单、禁区、示例回复等。
Agent 在决定使用该技能之后，才会（按产品实现）加载这一大段。
```

| 字段 / 部分   | 建议                                                   |
| ------------- | ------------------------------------------------------ |
| `name`        | 技能显示名；可与文件夹名相同，也可以不同               |
| `description` | **既写「做什么」，也写「何时用」**；这是触发匹配的关键 |
| 正文          | 流程、规范、禁止事项；宜可执行，避免空泛口号           |

记住：

> **元数据 ≈ 目录卡片；正文 ≈ 操作手册。**  
> 平时只靠卡片做发现；对上任务再读手册。

---

## Skill 在 Hubloom 里干什么？

Hubloom 把上面这套约定落到仓库的 **`skills/`** 目录：我们可以用 Markdown 写下领域 Know-how（先查什么、怎么确认、哪些是禁区），用来约束 Agent **按照实际的业务流程**，而不是只靠模型临场发挥。

在主路径上，Skill 的作用可以概括成三点：

1. **告诉 Agent「有哪些规矩」**  
   启动时扫描 `skills/*/SKILL.md`，把每份技能的**名片**（name + description）写进 Think 用的系统提示（「可用 Skills」）。模型先浏览目录，再决定要不要深读。

2. **按需给出「怎么做」**  
   任务和某张名片对得上时，再去读该 Skill 的**正文**（细则、禁令、话术）。正文进上下文之后，Agent 按规程行动。

3. **不代替业务调用**  
   Skill **说明规矩**；真正查数据、改状态，仍然走 MCP 的 `list_api` / `call_api`（或按规程拒绝代办、直接回复用户）。  
   没有「执行这个 Skill」的独立按钮——读完手册，还是要靠工具或说话把事做完。

和相邻模块的分工：

| 模块              | 在这条链上的角色                                      |
| ----------------- | ----------------------------------------------------- |
| **Skill**         | 业务怎么办、什么不能做（规程）                        |
| **MCP / OpenAPI** | 系统里有哪些接口、怎么调得通（能力）                  |
| **Tools**         | 把 `read_skill`、`list_api` 等挂成 Agent 可调用的工具 |
| **Runtime**       | 启动时注入名片、每轮挂上工具，把上面几块装配起来      |

### 流程例子：业务流程 Skill 如何带动 MCP

仓库里的 `select-before-act` 是典型「办事流程」Skill：用户要对列表里的某一条动手（删、改、看详情），但还没选定唯一对象时，**必须先查列表、展示候选、等用户选中**，禁止瞎猜 ID 直接写。

假设用户说：「把那个叫旺财的宠物删掉。」（未给确切 ID）

```text
用户：「删掉旺财」
        │
        ▼
① 模型看「可用 Skills」名片
   → 命中 select-before-act（列表选型后再动手）
        │
        ▼
② read_skill(skill="select-before-act")
   → 读入正文：先拉列表、展示最多 10 条、等用户选；
     删除还要二次确认；禁止未确认就 call_api 删除
        │
        ▼
③ list_api(tag=…)          ← MCP：发现该业务分组有哪些工具
   call_api(…列表工具…)     ← MCP：真正查出候选项
        │
        ▼
④ 交 Respond：把候选展示给用户（名称 + ID），停住等选择
        │
        ▼
⑤ 用户选定某一条，并确认「是，删除」
        │
        ▼
⑥ call_api(…删除工具…, id=用户选中的 ID)   ← 仍是 MCP 执行
        │
        ▼
⑦（规程要求时）再 call_api 拉一次列表，展示写后结果给用户核对
```

对照看职责：

| 步骤 | 谁在起作用                                                 |
| ---- | ---------------------------------------------------------- |
| ①②   | **Skill**：何时介入、先选后动、删除要确认                  |
| ③⑥⑦  | **MCP**（经 `list_api` / `call_api`）：查列表、删除、复核  |
| ④⑤   | **对话 / Respond**：把候选和确认交给用户，不静默替用户做主 |

Skill **没有**自己去发 HTTP；它只规定「第几步才能调哪个方向的 API、何时必须停」。  
MCP 侧有什么接口，仍以 OpenAPI / `list_api` 为准；Skill 正文里写的是**流程与禁令**，不是第二份接口文档。

---

## Hubloom 里怎么用上 Skill？（跟测试走）

完整对话链路里还有 Think / Runtime 装配；要先摸清「名片怎么来、正文怎么读」，可以直接跑仓库里的手工脚本 [`tests/test_skill.py`](../../tests/test_skill.py)。它把主路径拆成三步，打印结果给你看——**不必先起整个聊天服务**。

### 怎么跑

在**仓库根目录**执行（否则相对路径 `skills` 可能找不到）：

```bash
PYTHONPATH=src .venv/bin/python tests/test_skill.py
```

脚本入口会依次调用：加载名片 →（再）挂工具并 `read_skill` 读正文。

### 第一步：加载名片，拼进「系统提示」片段

对应 `test_load_skills`：

```python
skills = load_skills("skills")
prompt = build_skills_prompt(skills)
print(prompt)
```

| 调用                          | 作用                                                                        |
| ----------------------------- | --------------------------------------------------------------------------- |
| `load_skills("skills")`       | 扫描 `skills/*/SKILL.md`，读出每份的 id / name / description / body         |
| `build_skills_prompt(skills)` | **只**用 name + description 拼出「【可用 Skills】」文案，**不把正文塞进去** |

你应在终端看到类似下面这样（仓库默认 `skills/` 时的名片输出；description 可能随文件更新略有出入）：

```text
【可用 Skills】
以下为技能名片（name + description）。需要细则时调用工具 read_skill(skill=name)，再按返回的 SKILL.md 正文执行；同一 skill 每轮只读一次。
- account-access: 账号与访问控制（禁止代办敏感账号操作）：当 call_api 返回未登录/未授权/无权限 （如 401、403），或用户要求登录、退出、改密码、改用户资料、让 Agent 代调登录/ 改密/资料接口时使用。须拒绝代办并引导侧栏凭证或官方入口；不得 list_api/ call_api 去执行这些敏感操作。
- events: 业务事件驱动任务总册。当会话由 Webhook / POST /v1/events 触发，或用户提到 事件处理、locker.created、locker.offline、order.refund 等事件类型时使用。 具体步骤在 skills/events/ 下各分册 md；事件入站时 Runtime 会注入对应分册正文。
- select-before-act: 列表选型与关联绑定：当用户要删除、移除、禁用、查看详情、编辑某一条， 或创建/修改时字段需绑定其他业务数据，且未明确唯一 ID / 未选定关联对象时使用。 须先拉取并展示候选（默认最多前 10 条）供用户选择；删除在选定后仍须二次确认， 禁止猜测 ID 或未确认就 call_api 删除。写操作（增/改/删等）成功后，若有列表或 Lookup 接口，应再拉一次相关列表并展示，让用户确认当前结果。
```

注意：这里只有 **name + description**，**没有**各 `SKILL.md` 的正文——说明注入的是名片，不是整本手册。

这和 Runtime 启动时往 Think system 里注入的是同一类东西：模型先看到目录卡片。

源码：`src/skill/load.py`。

### 第二步：挂上 `read_skill` 工具

对应 `test_read_skill`：

```python
skill_tools = build_skill_tools(skills_dir="skills")
registry = ToolRegistry.from_tools(skill_tools)

print("【可用的工具列表】")
for tool in registry.list_definitions():
    print("【工具名称】", tool["name"])
    print("【工具描述】", tool["description"])
    print("【工具参数】", tool["parameters"])
```

| 调用                      | 作用                                                                                      |
| ------------------------- | ----------------------------------------------------------------------------------------- |
| `build_skill_tools(...)`  | 若目录里有 Skill，则构造 **一个** `read_skill` 工具（多个规程共用这一个入口，靠参数区分） |
| `ToolRegistry.from_tools` | 注册进工具表                                                                              |
| `list_definitions()`      | 取出给 LLM 看的工具 schema（name / description / parameters）                             |

你应在终端看到类似：

```text
【可用的工具列表】
【工具名称】 read_skill
【工具描述】 读取指定 Skill 的 SKILL.md 正文（操作细则）。仅当「可用 Skills」名片与当前任务匹配、且正文尚未出现在本轮上下文时调用。参数 skill 为目录 id（推荐，如 account-access）或 frontmatter name。同一 Skill 每轮最多成功读取一次；读完后按正文执行，禁止重复读取。本工具不执行业务，不能代替 list_api / call_api。
【工具参数】 {'type': 'object', 'properties': {'skill': {'type': 'string', 'description': 'Skill 目录 id 或 name，例如 account-access'}}, 'required': ['skill']}
```

要点：工具面里通常**只有一个** `read_skill`；具体读哪份规程，靠参数 `skill`（如 `account-access`），而不是为每个 Skill 各注册一个工具。

这和 Runtime `_make_runner` 里 `*skill_tools` 挂进 Registry 是同一意图。

源码：`src/tools/builtin/skill_tools.py`、`src/tools/registry.py`。

### 第三步：模拟调用，读出正文

对应 `test_tool_runner`（内部会再次走到第二步，再执行）：

```python
text, is_error = await tool_runner.run(
    "read_skill",  # 工具名称
    {"skill": "account-access"},  # 工具参数
)
print("【工具执行结果】")
print("【是否错误】", is_error)
print("【执行结果】", text[:200])  # 脚本只打印前 200 字
```

这里**不调用真实大模型**：手写工具名和参数，直接走 `ToolRunner`，假装 Think 已经决定「要读 account-access」。

你应在终端看到类似（正文被截断到约 200 字）：

```text
【工具执行结果】
【是否错误】 False
【执行结果】 # skill: account-access

# Account Access

本 Skill 规定：**对话 Agent 不代办登录、改密、改用户资料**；只处理权限失败时的说明，并引导用户到正确入口。

Hubloom 业务鉴权靠**会话透传**（侧栏「业务 Token」→ MCP）。聊天里收集密码、代调登录/改密/资料接口，一律禁止。

## 何时使用

- 工具结果为未登录 / To
```

说明：`False` 表示 Runner 认为执行成功；后面才是 `SKILL.md` 正文（以 `# skill: account-access` 开头）。完整正文比打印更长，可直接打开 `skills/account-access/SKILL.md` 对照。

同一轮里若再对同一 id 成功 `read_skill` 一次，会提示「已在本轮加载」（产品里由 Runtime 每轮开始时 `clear_read_skill_turn_state()` 清零）。本脚本若连续跑两次读同一 skill，第二次就可能打出该提示——正好用来理解「每轮只读一次」。

### 三步和真实对话的对应

| 测试里                               | 真实 Hubloom 对话里                                          |
| ------------------------------------ | ------------------------------------------------------------ |
| `build_skills_prompt` 打印的名片     | Think system 里的「可用 Skills」                             |
| `list_definitions` 里的 `read_skill` | 模型可调用的工具之一                                         |
| `ToolRunner.run("read_skill", …)`    | 模型发出 tool_call 之后，Execute 真正执行                    |
| （本脚本未覆盖）                     | 读完正文再按规程去 `list_api` / `call_api`——见上一节流程例子 |

读完并跑通这三步，你就已经摸到 Hubloom 使用 Skill 的核心：**扫文件 → 名片进提示 → 工具按需读正文。** Runtime 只是在启动/每轮对话时自动做完这些事，并接上 MCP 与编排循环。
