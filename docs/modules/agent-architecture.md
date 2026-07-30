# Agent 最终架构：Policy-Bounded Typed ReAct

> 状态：**最终落地目标规格**（讨论定稿；尚未改代码）。  
> 过程备忘见 [agent-design.md](agent-design.md)。若冲突，以本文为准。  
> **明确淘汰：A2UI / Present / 双通道定稿。** 等人用挂起确认或跨 run 追问；宿主自绘按钮/输入，不用 UI DSL。

---

## 1. 一句话（产品辨识度）

> **Hubloom Agent = 规程约束下的类型化办事环（Policy-Bounded Typed ReAct）**  
> 单环 Decide → `act` | `ask` | `await_confirm` | `finish`；业务规程可硬拦；观察进证据账；  
> **交互式入口可 run 内挂起等人（借鉴 Cursor）**；异步入口（企微/事件）用跨 run 交班。

不是通用聊天壳，也不是 A2UI 表单引擎。  
创新落在：**类型化动作 + 可执行 Playbook + 证据账 + 按入口切换的等待模式**。  
二开加 Skill/Tool 仍走「写文档 / 挂工具」，不要求改环（见 §13）。

---

## 2. 通俗讲解：解决什么问题、整体怎么走

名字拆开看就三块：

| 词 | 白话 |
| --- | --- |
| **ReAct** | 想一步 → 动手 → 看结果 → 再想；一条环办完，不再拆「思考模型 / 定稿模型 / 画表单」 |
| **Typed** | 每一步只能选规定好的动作：`act`（办事）、`ask`（问人）、`await_confirm`（等确认）、`finish`（收工） |
| **Policy-Bounded** | 公司规程（Skill→Playbook）能**拦住**违规动作，不是只靠模型「自觉」 |

### 2.1 它主要解决什么问题

| 痛点 | 没有这套时容易怎样 | 这套怎么挡 |
| --- | --- | --- |
| 企业要**办事**不只聊天 | 模型空口答应、不调 API | 主路径就是 `act` 调真实工具 |
| 参数不全就瞎调 | 直接 `addPet` 失败一堆 | 先 `ask`，问清再 `act` |
| 高风险写操作 | 一句话删数据 | `await_confirm`，人点头再执行 |
| 各厂流程不同 | 改代码堆 if/else | Skill 写成 Playbook，Gate **硬拦** |
| 架构太碎难嵌 | Think/Present/A2UI 多相位 | **单环**；入口只选 Wait Profile |
| 结论对不上工具 | 失败却说成功 | Journal 记账；finish 可 cite |
| 网页想等人、企微不能挂 HTTP | 一种等人方式打天下 | **Wait Profile** 分挂起 / 跨轮 / 禁止等 |

### 2.2 整体流程（一张嘴能说完）

```text
用户说话（或事件进来）
    → Session 开一个 Run，拼好上下文
    → 反复：
         Decide 选一个动作
         Gate 检查合不合规程
         合规则执行（调工具 / 问人 / 确认 / 收工）
         结果写入 Journal
    → 问人或确认：按入口挂起或结束本轮
    → finish：给出总结，Run 结束
```

插件（MCP、A2A、RAG、Memory、Skill）都挂在环外：**换插件不换环**。

### 2.3 例子 A：加宠物（网页，可挂起）

假设 Wait Profile = `interactive`（人对着屏幕）。

1. 用户：「帮我加一只宠物。」  
2. **Decide** → `ask`：「叫什么名字？什么品种？」  
3. Run **挂起**，页面出输入框（普通 UI，不是 A2UI）。  
4. 用户回复：「小花，猫。」→ **resume 同一 Run**。  
5. **Decide** → `act(addPet, {name: 小花, …})`。  
6. **Gate** 放行 → MCP 调企业 API → 成功观察进 **Journal**。  
7. **Decide** → `finish`：「已经加上小花。」（可带 cites）  
8. 终态 `completed`。

### 2.4 例子 B：有规程时（Policy 出场）

开发者 Skill 写了：「新增宠物后必须再调用登记接口；禁止直接 `finish`。」

1. 加宠成功后，模型若直接 `finish` → **Gate 拒绝**（必经未完成）→ reject 观察 → 再 Decide。  
2. 模型改去 `act(registerPet, …)` → 成功 → 才允许 `finish`。  

用户仍觉得是「Agent 帮我办完了」；差别是**厂规写在 Skill 里**，不用改 Agent 内核。

### 2.5 例子 C：企微（不能挂着等）

Wait Profile = `turn_based`：

1. 用户：「加宠物。」→ `ask` → **本 Run 结束**，消息推到手机。  
2. 用户再回「小花，猫」→ **新 Run**，带着 pending「在加宠物」继续 `act` → `finish`。  

同一套环，只是「等人」从挂起换成跨轮，避免企微回调挂死。

### 2.6 和「普通聊天机器人」差在哪

| | 陪聊 Bot | 本架构 |
| --- | --- | --- |
| 中心 | 把话说圆 | **把事办完或问清** |
| 下一步 | 自由发挥 | **只能 Typed 动作** |
| 厂规 | 提示里求求模型 | **Gate 可硬拦** |
| 等人 | 往往含糊 | **挂起或跨轮，入口明确** |

读完本节，应能用「加宠物」走通一遍环，并说出它解决的是办事、缺参、确认、厂规、多入口，而不是再发明一套 UI 协议。更细的分层与不变量见后面各节。

---

## 3. 从哪里借鉴、哪里自研

| 来源 | 借鉴什么 | Hubloom 怎么用 |
| --- | --- | --- |
| Cursor 等交互式 Agent | 单环 ReAct；危险动作执行前卡住；**同一 run 挂起，人点了继续**；少相位所以快 | 网页对话默认 **HITL pause** |
| Cursor Auto-review 思路 | 执行前闸门要快、堵在 Exec 前 | **Policy / Exec Gate**（安全 + 业务规程），不是第二套聊天模型 |
| Hubloom 自身 | OpenAPI 办事、Skill 厂规、多入口 | **Playbook 硬拦**、契约向 `act`、入口 **Wait Profile** |

**坚决不借鉴**：把可操作 UI 协议做进 Agent 内核（已淘汰的 A2UI 路线）。

---

## 4. 内核总图

```text
┌─────────────────────────────────────────────────────────────────────────────┐
│                           Hubloom Agent Kernel                              │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│  ┌─────────────┐  触发+Wait Profile  ┌─────────────────────────────────┐   │
│  │   Session   │◄───────────────────│        Run Loop（单 Run）         │   │
│  │  (边界管理) │                    │                                 │   │
│  │ • Run 边界  │                    │  1. Assemble 上下文               │   │
│  │ • 历史组装  │                    │     · Session 历史               │   │
│  │ • pending   │                    │     · Evidence Journal 摘要      │   │
│  │ • 串行/防重入│                    │     · Policy 注入合法动作集       │   │
│  │ • 终态写入  │                    │     · pending intent / slots     │   │
│  │ • resume    │                    │              ▼                    │   │
│  └──────┬──────┘                    │  2. Decide（唯一「想」）            │   │
│         │                           │     → act | ask | await_confirm   │   │
│         │                           │       | finish（互斥解析）          │   │
│         │                           │              ▼                    │   │
│         │                           │  3. Policy / Exec Gate 硬拦截      │   │
│         │                           │     · 合法集 / 必经 / 须确认        │   │
│         │                           │     · 违规 → reject 观察 → 回 Decide│  │
│         │                           │       （默认不整 Run 判死）         │   │
│         │                           │              ▼                    │   │
│         │                           │  4. 分派执行                       │   │
│         │                           │     · act → Tool/MCP/A2A → 观察   │   │
│         │                           │     · ask / await_confirm         │   │
│         │                           │         → 按 Wait Profile：        │   │
│         │                           │           挂起 resume 或结束 Run   │   │
│         │                           │     · finish → 结束 Run（完成）    │   │
│         │                           │              ▼                    │   │
│         │                           │  5. Evidence Journal 入账          │   │
│         │                           │              ▼                    │   │
│         │                           │  6. 终态（见 §11）                  │   │
│         │                           └────────────────┬──────────────────┘   │
│         │                                            │                      │
│         │                                            ▼                      │
│         │                           ┌────────────────────────────────┐      │
│         │                           │ 对外事件流（SSE/WS 等，编码层） │      │
│         │                           │ · step / tool / 文本增量        │      │
│         │                           │ · awaiting_user（等待载荷）     │      │
│         │                           │ · run_complete（终态）          │      │
│         │                           │ · 不包含 A2UI 描述符            │      │
│         │                           └────────────────────────────────┘      │
│         ▼                                                                   │
│  ┌─────────────────────────────────────────────────────────────────────┐    │
│  │                     插件端口（Plugins，不改环形状）                   │    │
│  │  ┌──────┐ ┌──────┐ ┌──────┐ ┌──────┐ ┌──────────────┐             │    │
│  │  │ MCP  │ │ A2A  │ │ RAG  │ │Memory│ │ Skill→Playbook│             │    │
│  │  └──────┘ └──────┘ └──────┘ └──────┘ └──────────────┘             │    │
│  └─────────────────────────────────────────────────────────────────────┘    │
└─────────────────────────────────────────────────────────────────────────────┘
```

要点：

- **Assemble 时**注入合法动作集（软约束）；**Exec 前**再硬校（双保险）。  
- **Policy reject** = 观察回环，可熔断为 `ask`/`finish`；**不是**一拒就整 Run `REJECTED`。  
- **Ask / Confirm** 行为由 **Wait Profile** 决定，不是写死「一律结束 Run」。

---

## 5. 分层职责

| 层 | 职责 |
| --- | --- |
| **Session** | Run 边界、历史、pending、串行/防重入、终态写入、interactive 下 `resume` |
| **Decide** | 唯一「想」：在合法动作集中选下一步 |
| **Policy / Playbook** | 允许·禁止·必经；哪些 act 须先确认；编译自 Skill |
| **Exec Gate** | 执行前硬校验 + 可选风险策略；reject → 观察 |
| **Exec** | 调 ToolRunner；等待动作按 Profile 挂起或结束 |
| **Evidence** | Journal；`finish` 可 cite |
| **Events** | 进度/等待/终态；**无 A2UI** |

---

## 6. 类型化动作（封闭集）

| 动作 | 含义 | 之后 |
| --- | --- | --- |
| `act(name, args)` | 办事/查询/委托（**A2A 也是 act**） | Gate → 执行 → Observation → 再 Decide |
| `await_confirm(prompt, payload?)` | 高风险点头 | 按 Wait Profile 挂起或跨 run / 降级 |
| `ask(question, slots?)` | 缺参、澄清 | 同上 |
| `finish(summary, cites?)` | 办完或说明清楚 | **结束 Run**；终稿=summary |

Decide 互斥（落地必做）：

- 同一步：`finish` / `ask` / `await_confirm` 与继续 `act` 不得糊成乱输出。  
- 默认 **串行** 多个 `act`；并行后置为显式优化。

**没有** Present、A2UI、默认第二次定稿模型。

---

## 7. Wait Profile（等人）

| Profile | 适用入口 | `ask` / `await_confirm` |
| --- | --- | --- |
| **`interactive`** | 网页对话等 | **Run 内挂起** → 宿主自绘按钮/输入 → **`resume` 同一 Run** |
| **`turn_based`** | 企微、部分 webhook | **结束 Run**，终态 `waiting_user`；下一条用户消息 = **新 Run**（带 pending） |
| **`no_wait`** | Events 等无人值守 | **禁止等待**：误用则降级 `finish`/`failed`，绝不挂死 |

等待策略**跟入口走**，不跟单个 Skill 走——写 Skill 的人无感。

---

## 8. Playbook（规程硬边界）

Skill / 事件分册 → **可执行 Playbook**（最小子集先落地）：

- 禁止动作列表  
- 必经步骤 id（未完成则禁止 `finish`）  
- 须先 `await_confirm` 的 `act` 名  

Gate 违规 → reject 观察 → 回 Decide；**连续同因 reject 熔断**，避免死循环。  
无 Playbook = 纯能力环（仍受工具面与 Wait Profile 约束）。

---

## 9. Evidence Journal

每次 Observation 入账（**摘要进模型**，全量可旁路）。  
鼓励 `finish(cites=[…])`；后续可加强「未解释的失败观察不可宣称成功」。

---

## 10. Session 锚点

| 字段 | 用途 |
| --- | --- |
| pending intent | 在办什么（跨 run / 挂起续办） |
| slots | 已收集 / 仍缺 |
| awaiting | interactive 挂起句柄 |

挂起恢复：用户输入/确认 → Observation → 清 awaiting → 继续 loop。  
跨 run：新 Run Assemble 读 pending，不单靠长历史猜测。

---

## 11. 终态不变量

| 情况 | 终态 |
| --- | --- |
| `finish` | `completed` |
| interactive 下 ask/confirm | Run **未结束**，`awaiting_user`（可 resume） |
| turn_based 下 ask/confirm | Run **结束**，`waiting_user` |
| no_wait 误用等待 | `failed` 或说明性 `completed`，不挂起 |
| 步数触顶 | `incomplete` + 摘要 |
| 取消 | `cancelled`；已发出副作用不自动回滚 |
| 流断/内核异常 | `failed` |
| 单次 Policy reject | **不是终态**；入 Journal 后回环（熔断后才 ask/finish） |

同 session：宿主/Runtime **串行** + 内核防重入（详见 **§20.1**）。interactive 挂起态须 **SessionStore 端口化**，多实例外置（**§20.2**）。

---

## 12. 对外契约（瘦）

1. **输入**：触发 + `session_id` + 鉴权 + **Wait Profile**  
2. **过程**（可选）：step / act / 观察 / 文本增量 / `awaiting_user`（prompt + payload）  
3. **输出**：终稿（若有）+ 终态  
4. **interactive**：另需 `resume(run_id, user_input | confirm)`  

宿主画自己的确认按钮即可。**事件流不携带 A2UI 描述符。**

---

## 13. 二开不变量（Skill / Tool 要简单）

> 业务二开优先：**加/改 Swagger 或 MCP、实现并挂载 Tool、在 `skills/` 写规程文档。**  
> **不要求**理解 Decide 互斥、改 `loop`、或为每个 Skill 声明 Wait Profile。

| 扩展 | 预期做法 | 不应要求 |
| --- | --- | --- |
| 新业务 API | 配契约 / 挂 MCP | 改 Agent 环 |
| 新 Tool | `BaseTool` + Runtime 装配 | 改 Gate 源码（高风险仅在 Skill/配置标 `confirm`） |
| 新 Skill | Markdown（+ 可选 frontmatter：禁止/必经/须确认） | 手写 Python 状态机 |
| 新入口 | 调同一 Kernel，选 Wait Profile | 复制一套 Agent |

复杂留在平台（Playbook 编译、Gate、挂起存储）；泄漏到业务二开即设计失败。

---

## 14. 建议代码切分

| 模块 | 内容 |
| --- | --- |
| `session` | 组装、pending、run / resume |
| `loop` | Decide ↔ Exec 主循环 |
| `actions` | 动作 schema / 互斥解析 |
| `policy` | Playbook |
| `gate` | Exec 前校验 |
| `evidence` | Journal |
| `wait` | Wait Profile、挂起与跨 run |
| `events` | 进度 / awaiting / 终态 |
| Exec 端口 | ToolRunner（插件在端口外） |

删除主路径：`present`、`a2ui_*`、双 Respond、A2UI 向 `turn_state`。

---

## 15. 创新怎么讲（对外）

> Hubloom Agent：在 **业务规程** 约束下的 **类型化办事环**；工具与 A2A 同构为 `act`；结论可回溯证据账；  
> 人对着屏幕时可 **挂起确认再继续**，系统推事件时 **绝不瞎等**——交互留给宿主，不用 A2UI。

---

## 16. 已知风险（预演摘要）

- Decide 同时「说话 + 调工具」→ 必须互斥解析  
- Playbook 编译过弱 → 硬拦名存实亡（先做禁止表 + 必经 id + 须确认名）  
- Journal 膨胀 → 摘要进模型  
- interactive 多实例 → awaiting 外置  
- no_wait 误 ask → Gate 强制降级  
- 二开若被迫改 loop → 违反 §13，需改设计而非加文档补丁  

---

## 17. 相对讨论演进

| 更早想法 | 本文定稿 |
| --- | --- |
| Think / Present / A2UI / 双 Respond | **单环 Typed ReAct** |
| 等人一律结束 Run | **Wait Profile：可挂起或跨 Run** |
| Policy 拒 = 整 Run 失败 | **reject 观察回环 + 熔断** |
| 事件流带 A2UI | **删除** |
| 二开是否变重 | **§13 明确要浅** |

---

## 18. 后续落地

见下一节 **开发步骤拆解**（推荐顺序）。  
**动手写代码前**须先读并遵守 **§20 开工不变量**（并发、挂起、鉴权、双轨等）。

---

## 19. 开发步骤拆解（推荐）

原则：**先长出可跑的单环，再加等人与规程，最后清旧债、接入口。**  
每步结束都应有可演示/可测的行为；小模块尽量可单测，不依赖示例站全开。

### 19.1 小模块清单（目标包结构）

建议在 `src/agent/` 下逐步长成（名称可微调，职责别混）：

| 小模块 | 职责 | 主要产出 |
| --- | --- | --- |
| `actions` | 动作 schema、Decide 输出解析、互斥规则 | `Act` / `Ask` / `AwaitConfirm` / `Finish` |
| `evidence` | Journal 追加、摘要裁剪、cites 辅助 | `EvidenceJournal` |
| `events` | 进度 / awaiting / 终态事件（精简现有 `events.py`） | 对外事件枚举 |
| `session` | Run 启停、pending/slots、防重入、终态写入接口 | `SessionStore` 端口（内存先、外置后） |
| `loop/decide` | 一次模型调用 → 解析为 Typed 动作 | 替代今日 `think` 的主路径 |
| `loop/exec` | 执行 `act`（调现有 ToolRunner） | 替代今日 `execute` 的接线 |
| `gate` + `policy` | Playbook 模型 + Exec 前校验 | reject 观察；先做最小 Playbook |
| `wait` | Wait Profile、挂起 / 跨 run / no_wait 降级 | `pause` / `resume` / 结束等待 |
| `kernel` / `run` | 串起 Assemble→Decide→Gate→Exec→Journal | 新 `run_stream`（或并行旧入口一段时间） |
| `assemble` | 历史 + Journal 摘要 + 合法动作说明进 prompt | 从现有 `assemble.py` 瘦身 |
| `prompts` | 单环 system（无 Present/A2UI Respond 文案） | 新 prompt |

**本期删除或移出主路径（稍后步骤做）：** `present`、`a2ui_*`、双 Respond、`turn_state` 的 A2UI waiting。

插件（MCP / A2A / RAG / Memory / Skill 文件）**不在 Agent 内核步骤里重写**；Skill→Playbook 编译可单独一步挂上。

### 19.2 分几步开发

```text
Step 0  契约冻结（文档/事件/终态）     ← 已基本完成，开工前再核对一页
Step 1  最小单环（无挂起、无 Playbook）
Step 2  Typed 动作互斥 + Journal
Step 3  Wait Profile（先 turn_based，再 interactive resume）
Step 4  Gate + 最小 Playbook（Skill frontmatter）
Step 5  拆掉 A2UI/Present 旧路径，Runtime/示例站切换
Step 6  打磨：外置挂起态、熔断、no_wait、观测与单测补齐
```

---

#### Step 0 — 契约冻结（0.5 步）

- 终态枚举、`awaiting_user` 事件字段、`resume` 参数形状写死（§11–§12）。  
- **落实 §20 开工不变量**（串行、挂起竞态、鉴权快照、Decide 协议、双轨）。  
- 明确：旧 `run_stream(present_mode=…)` 双轨策略（§20.7）。  

**验收**：前后端/入口同学看完 §12 + §20 知道怎么接；字段名与互斥规则不再改口。

---

#### Step 1 — 最小可跑单环（核心骨架）

**做：**

- `actions`（可先只支持 `act` + `finish`，`ask` 用「finish 带问句」临时顶上也可以，但建议直接留 `ask` 类型）  
- `loop/decide` + `loop/exec` + 新 `run` 主循环  
- Assemble 用现有 memory + 工具表；**一条 system**  
- StreamError → `failed`（顺手修生产坑）

**先不做：** Playbook、挂起、A2UI 删除（可仍走旁路旧 API）。

**验收：** 配置好 MCP 时，「查宠物 / 参数齐加宠物」能 `act`→`finish` 跑通；无 Present/Respond 第二次调用。

---

#### Step 2 — Typed 互斥 + Evidence Journal

**做：**

- Decide 输出互斥解析（不能又 act 又 finish）  
- `evidence`：每次观察入账；Assemble 带摘要  
- 事件：`step` / tool 结果 / `run_complete`

**验收：** 单测覆盖「非法双动作」；日志/事件里能看到 Journal id。

---

#### Step 3 — Wait Profile（等人）

建议再拆两小步：

**3a `turn_based`（更简单）**

- `ask` / `await_confirm` → 结束 Run，`waiting_user`  
- Session `pending` + slots  
- 下一条用户消息新 Run 续办  

**验收：** 缺参两轮对话（类似企微）能办完加宠物。

**3b `interactive`（学 Cursor）**

- Run 内挂起 + `resume`  
- 事件 `awaiting_user`；示例站普通按钮（**非 A2UI**）  
- **SessionStore 端口化**（内存实现可先用）；**多副本禁止只靠进程内存**（§20.2）  
- 落实挂起竞态与断线策略（§20.3–§20.4）

**验收：** 网页一点确认/填参，同一 run_id 继续 `act`→`finish`；单测覆盖「挂起中新消息」互斥。

**3c `no_wait`**

- 误 ask → 降级 finish/failed  

**验收：** 事件入口单测不会永久 waiting。

---

#### Step 4 — Gate + 最小 Playbook

**做：**

- `policy`：禁止列表、必经 step id、须 confirm 的 tool 名（frontmatter）  
- `gate`：Exec 前硬拦；reject→观察回环；同因熔断  
- Skill Loader → Playbook（最小编译，不追求全文理解）

**验收：** Skill 写「禁止未登记就 finish」时，模型提前 finish 会被打回并最终走登记。

---

#### Step 5 — 拆除旧路径 + 宿主切换

**做：**

- Runtime 去掉 `present_mode` / a2ui system 默认  
- 示例站改接新事件与 resume；删 A2UI 渲染主路径  
- 删除或归档 `present.py`、`a2ui_*`、旧双 Respond  
- 企微 / Events 显式传入 Wait Profile  

**验收：** 主路径文档与 demo 只讲单环；旧 A2UI 不再出现在默认配置。

---

#### Step 6 — 硬化与收尾

- awaiting / pending **外置**（Redis 等）  
- 取消、触顶 `incomplete`、context dump 门控  
- 并行 `act`（可选后置）  
- 模块文档 `agent.md` 正文按新架构重写  

**验收：** 多实例下 interactive 挂起可恢复；清单上的风险项有对策或明确不做。

---

### 19.3 步骤 ↔ 模块对照

| 步骤 | 主要动到的小模块 |
| --- | --- |
| 1 | `actions`, `decide`, `exec`, `run`, `assemble`, `prompts` |
| 2 | `actions` 互斥, `evidence`, `events` |
| 3 | `wait`, `session`,（示例站 resume UI） |
| 4 | `policy`, `gate`, Skill→Playbook |
| 5 | `runtime`, examples, 删除旧 loop 文件 |
| 6 | `session` 外置, 观测, 文档 |

### 19.4 人力与依赖提示

- Step 1–2 可纯后端 Agent；Step 3b 需要示例站一点点 UI。  
- Step 4 依赖 Skill 格式约定，可与文档同步。  
- Step 5 是「破坏性切换」，建议 flag 或短双轨，避免半周不能演示。  
- **不要**在 Step 1 同时做挂起+Playbook+拆 A2UI——范围会炸。

### 19.5 建议的下一步开工命令

1. 确认 §20 已写入文档且团队无异议。  
2. 从 **Step 1** 开——新建 `actions` + 新 loop 骨架，**`run_stream_v2`（或 flag）双轨**旧 `run_stream`。  
3. 验通后再进 Step 2。

---

## 20. 开工不变量（补强：并发 / 挂起 / 鉴权 / 双轨）

> 本节是审查结论落地：**需求方向可开工，但下列规则必须遵守**，否则 Step 3+ 上多用户/多实例会翻车。  
> 与正文冲突时，**以本节为准**（并回改对应小节）。

### 20.1 同 session 串行：职责切分

| 层 | 职责 |
| --- | --- |
| **入口 / Runtime** | 保证同一 `session_id` 上 **同时只有一个活跃 Agent 执行**（锁或队列；可与 `im/session_queue` 对齐或共用约定） |
| **Agent 内核** | **防重入断言**：若该 session 已有 `running` / `awaiting_user` 的 Run，拒绝再 `begin`（或返回明确错误），不默默并行 |

不变量：**串行是平台能力，不是「示例站碰巧有一把全局锁」。**  
Web、企微、Events 接同一 Kernel 前，必须接上 session 串行；Step 1 可先内核断言 + 单测，多入口接线前补齐锁/队列。

### 20.2 interactive 挂起与多实例

- Step 3b 起：**SessionStore 必须是端口**（`get/set` pending、awaiting、run 状态）。  
- **内存实现**仅允许：单进程开发 / 单副本演示。  
- **多副本或生产**：必须外置（如 Redis）；禁止「内存挂起 + 负载均衡多实例」。  
- Step 6 完成外置默认实现；上线 checklist 含此项。

### 20.3 挂起期间的竞态（写死）

当 Run 处于 `awaiting_user`：

1. **只接受**匹配的 `resume(run_id, …)`（建议带一次性 `await_token`，防重放）。  
2. **普通新用户消息**（新 `begin_run`）策略定为：  
   > **拒绝**（返回「请先完成确认/回答，或先 cancel」）。  
   > 若产品要「新消息作废挂起」，必须显式 `cancel` 再 `begin`，不静默双开。  
3. 同一 `run_id` 并发两个 `resume`：第二个失败或幂等忽略（Store 用 CAS / 锁）。

### 20.4 SSE 断开 ≠ 取消 Run

- 浏览器刷新、SSE 断开：**默认不** `cancel` 挂起中的 Run。  
- 客户端重连后可用 `run_id` + `resume` 继续（状态在 SessionStore）。  
- 提供显式 `cancel(run_id)`。  
- 挂起态 **TTL**（建议默认 30 分钟，可配）：超时 → `cancelled` 或 `failed`，释放 session 槽位。

### 20.5 鉴权绑在 Run 上

- `begin_run` 时把鉴权上下文（如 Bearer）**快照进 Run**（或强制后续 `resume`/续跑携带并校验同一主体）。  
- Exec 调工具时**只用该 Run 的鉴权快照**，避免 resume 丢 token 或串用户。  
- turn_based 跨 Run：新 Run 用**当次请求**的 token；pending 只存意图/槽位，不存明文长期密钥到可泄漏日志。

### 20.6 MCP / 工具并发（旁路依赖）

- Agent 单环**不解决** MCP stdio 单管道争用。  
- **生产多用户**：应使用独立 HTTP MCP（或等价可并发运输），见 MCP Adapter 双传输设计。  
- 上线 checklist：Agent 新环 + MCP HTTP；勿在仍用全局 `_run_lock` 护 stdio 时宣称「已支持多用户并发」。

### 20.7 Decide 如何产出 Typed 动作（Step 1 锁定）

**选定协议（实现按此做，中途不改口）：**

- **业务 `act`**：走现有工具面（`list_api` / `call_api` / A2A / 其它 `BaseTool`），即模型的 tool_calls。  
- **控制动作**：专用控制 tool（推荐名）：`agent_ask`、`agent_await_confirm`、`agent_finish`（名称可微调，但语义固定）。  
- **互斥**：同一步若同时出现业务 tool_calls 与控制 tool → 非法，重试或报错观察。  
- **无任何 tool_call 的纯文本**：视为非法或强制收成 `agent_finish`（实现选一种并写进 `actions` 单测；推荐 **收成 finish**，避免干跑）。

发现类只读（如 `list_api`）：Playbook **默认不禁**；禁止/须确认针对写操作与点名 tool。

### 20.8 Playbook 默认姿态

- 无 Playbook = 纯能力环。  
- 有 Playbook：禁止列表 + 必经 id + 须 confirm 的 tool 名。  
- **默认放行** `list_api` 及标明 read-only 的工具，除非 Playbook 显式禁止。

### 20.9 双轨与文档债

- Step 1–4：**新入口** `run_stream_v2` 或 `HUBLOOM_AGENT_V2=1`；旧 `run_stream`（含 A2UI）保留可演示。  
- Step 5：切换默认；删除/归档 A2UI 主路径。  
- 同步改产品文案（如 `what-is-hubloom` 双通道 A2UI）——**最迟 Step 5**，避免对外叙事与实现长期打架。

### 20.10 并发场景速查

| 场景 | 不变量 |
| --- | --- |
| 同 session 连发 | 入口串行 + 内核防重入 |
| 多实例 + 挂起 | SessionStore 外置 |
| 挂起中又发新消息 | 拒绝；须先 resume 或 cancel |
| SSE 断开 | 不自动 cancel；TTL 回收 |
| resume 鉴权 | Run 快照 / 同主体 |
| Events 误 ask | `no_wait` 降级 |
| 多用户调 MCP | 依赖 HTTP MCP，非 Agent 环内解决 |

### 20.11 Step 0 完成标准（可勾选）

- [ ] §20.1–§20.10 已评审无异议  
- [ ] Decide 控制 tool 名称写入 `actions` 草案（可与 Step 1 同一 PR）  
- [ ] 双轨开关名称确定（`run_stream_v2` 或 env flag）  
- [ ] 挂起 TTL 默认值写入配置草案（可先常量）  

全部勾选后 → **开始 Step 1 代码**。
