# Memory

## Memory 是什么？

在 Agent 语境里，**Memory（记忆）**解决的是：模型本身**不会**自动记住你们之间的每一轮对话，也不会自动跨天记住「用户是谁、偏好什么」。若要让对话连贯、或跨会话还能用上过往信息，就要由系统在外面**存**和**取**。

通常可以先分两层来理解（名字因产品而异，意思相近）：

| 层                      | 通俗理解                            | 典型用途                                               |
| ----------------------- | ----------------------------------- | ------------------------------------------------------ |
| **会话记忆 / 对话历史** | 这一次聊天的「聊天记录本」          | 多轮上下文：用户刚说了什么、助手回了什么、调过哪些工具 |
| **长期记忆**            | 从多次对话里提炼出的「笔记 / 摘要」 | 跨会话：用户偏好、稳定事实、重要情节；需要时再检索出来 |

和邻近概念的差别也宜先分清：

|                    | 大致回答                                               |
| ------------------ | ------------------------------------------------------ |
| **Memory（会话）** | 这一轮对话里已经发生过什么（消息级历史）               |
| **Memory（长期）** | 跨会话值得保留、可检索的沉淀                           |
| **Skill**          | 办事**规矩**怎么写、何时遵守（规程，不是聊天记录）     |
| **RAG / 文档检索** | 外部手册、知识库里有什么（文档，不是「我们聊过什么」） |

设计上常见做法是：

1. **每轮对话**把新消息写入会话存储，拼上下文时再读出（并可对过长历史做裁剪）；
2. **可选地**在后台或事后把对话提炼成长期条目，需要时用查询去召回——而不是把全部历史永久塞进每一次提示。

---

## 用两个例子建立感觉

### 生活中：点外卖

想象你和店员打电话点餐：

| 场景                                                                                         | 像哪一层记忆    | 为什么                                             |
| -------------------------------------------------------------------------------------------- | --------------- | -------------------------------------------------- |
| 同一通电话里：「就要微辣」「刚才那份多加一份米饭」                                           | **会话记忆**    | 店员要记得**这通通话**里你说过的话，否则对不上     |
| 挂断后过了三天，你再打来：「还是老样子，少麻多香菜」——店员笔记本上写着「常客：少麻、多香菜」 | **长期记忆**    | 这不是某一通电话的逐字稿，而是提炼过的**偏好笔记** |
| 墙上贴着「过敏原必问、现金不找零」的店规                                                     | **不是 Memory** | 那是办事规矩（更像 Skill），不是「你们聊过什么」   |
| 柜台旁的《菜单》小册子                                                                       | **不是 Memory** | 那是对外知识（更像 RAG / 文档），不是聊天记录      |

要点：同一通电话靠「聊天记录」连贯；跨天靠「笔记本摘要」；店规和菜单是别的东西。

### Agent 里：查柜子再追问

假设用户和业务 Agent 这样聊：

1. 用户：「帮我查一下 A 区柜子状态。」
2. Agent 调业务接口，回复：「A 区 3 号空闲，5 号占用。」
3. 用户：「那 3 号帮我占用一下。」

若**没有会话记忆**，第 3 句里的「3 号」模型可能对不上「刚才查的是 A 区」，甚至忘掉已经查过。  
有会话记忆时，系统会把第 1～2 步的消息（含工具过程）留在本 `session` 的历史里，第 3 步拼上下文时还能看见，对话才能接上。

若用户**第二天**还想用上「我喜欢少麻」这类偏好：靠的是（可选的）**长期记忆**里有没有沉淀过这条笔记，而不是把昨天每一句聊天再播一遍。  
在 Hubloom 里还要注意：长期记忆和会话记录挂在**同一个隔离键**（`session_id` / `namespace`）下——换用户就要换键；并不是「新开一个聊天窗口就自动共用全站笔记本」。详情见下一节。

对照：

| 用户行为                            | 主要靠什么                             |
| ----------------------------------- | -------------------------------------- |
| 同一隔离键下追问、「刚才那个」      | **会话记忆**                           |
| 同一用户键下、隔天还想起偏好 / 事实 | **长期记忆**（可选；与会话共用隔离键） |
| 「删除前必须先选列表」这类规矩      | **Skill**                              |
| 「产品手册里柜子编号规则」          | **RAG / 文档**（若开启）               |

一句话：

> **Memory 管「记得住什么、什么时候拿出来」；不管业务 API 怎么调，也不管办事规程怎么写。**

---

## Memory 在 Hubloom 里怎么落地？

前面用「一通电话 / 隔天笔记本」区分**存什么**。到了 Hubloom，还要先钉死另一件事：**存在谁的名下**。

### 隔离键：`session_id`（同时也是 namespace）

Runtime 每轮会带一个 **`session_id`**，创建记忆时把它当作 **`namespace`** 传给 `create_memory_manager`：

```python
create_memory_manager(
    namespace=session_id,  # 会话历史 +（若开启）长期记忆，都挂在这个键下
    db_path=...,
    vector_backend="none",  # 示例主路径常先关掉长期向量
    graph_backend="none",
)
```

在当前用法里，可以把它理解成：**一个用户 / 一条业务会话线对应一个 id**。这个 id 会同时框住：

| 框住什么               | 含义                                                                  |
| ---------------------- | --------------------------------------------------------------------- |
| **会话记录**           | 这个 id 下的多轮聊天流水（用户 / 助手 / 工具消息）                    |
| **长期记忆**（若开启） | 同样挂在这个 **namespace** 下的沉淀与检索，**不是**全站共用一本笔记本 |

因此：

- **同一 `session_id`** → 读到的是「这个用户 / 这条线」的聊天记录；若开了长期记忆，搜到的也是**他名下**的笔记。
- **换成另一个用户的 id** → 会话记录换绑，长期记忆也换绑到那个 id；**不会**还留在上一个用户的库里。
- **不要**理解成：会话按电话本分户，长期记忆却是所有人共享的全局库——以当前 Hubloom 装配方式，**两层共用同一隔离键**。

> 「一通电话」只适合形容：在**同一个 id 里**多轮怎么接得上。  
> 它**不**表示长期记忆跟这个 id 无关。

### 默认开什么、可选开什么

在**同一个** `session_id` / `namespace` 之下：

|              | 存的内容                                    | 主路径默认                                                 |
| ------------ | ------------------------------------------- | ---------------------------------------------------------- |
| **会话记录** | 这一条线上的逐条消息                        | **有**（多轮聊天靠它）                                     |
| **长期记忆** | 提炼后的偏好 / 事实等，按需 `search_memory` | **常关**（`vector_backend` / `graph_backend` 可为 `none`） |

关掉长期后端时：这个 id 下的**聊天流水账还在**；只是没有跨会话向量 / 图检索。  
打开长期后端时：流水账和笔记仍都落在**这个 id** 下，换用户就要换 id。

部署与开关见进阶：[会话与记忆](../advanced/memory.md)。

### 和 Skill / RAG 的差别（避免再混）

|                        | 和 `session_id` 的关系                                        |
| ---------------------- | ------------------------------------------------------------- |
| **会话 / 长期 Memory** | **按 id 隔离**；换 id 就换绑到对应用户 / 会话线               |
| **Skill**              | 规程在 `skills/`，一般**不按用户 id 各备一份**                |
| **RAG**                | 文档库通常是共享知识，也**不是**「每个 session 一本聊天记录」 |

---

## 会话记录怎么写入 / 读出？（跟测试走）

完整对话里，Runtime / Agent 会自动 `remember`、拼上下文时再 `recall`。要先摸清「同一隔离键下存了什么」，可以跑仓库脚本 [`tests/test_memory_conversation.py`](../../tests/test_memory_conversation.py)：只演示 **conversation**，长期后端关掉，**不必起聊天服务**。

### 怎么跑

在**仓库根目录**执行：

```bash
PYTHONPATH=src .venv/bin/python tests/test_memory_conversation.py
```

### 脚本在做什么

核心是：写一整轮「用户 → 助手要工具 → 工具结果 → 助手终答」，再 `recall`（与 Runtime 主路径同形，只是手写消息）：

```python
session_id = "demo-user-1"
call_id = "call_list_1"

memory = create_memory_manager(
    namespace=session_id,       # 隔离键：会话（+ 若开启的长期）都挂这里
    db_path=...,
    vector_backend="none",
    graph_backend="none",
)

# 1、用户
await memory.remember(..., message=Message(role=Role.USER, content="帮我查一下 A 区柜子"))
# 2、助手发起工具（content 可为空，带 tool_calls）
await memory.remember(
    ...,
    message=Message(
        role=Role.ASSISTANT,
        content="",
        tool_calls=[ToolCall(id=call_id, name="call_api", arguments={...})],
    ),
)
# 3、工具回传（role=tool，tool_call_id 对齐上一步）
await memory.remember(
    ...,
    message=Message(
        role=Role.TOOL,
        content='[{"id": "3", "zone": "A", "status": "空闲"}]',
        tool_call_id=call_id,
        name="call_api",
    ),
)
# 4、助手终答
await memory.remember(
    ...,
    message=Message(role=Role.ASSISTANT, content="A 区 3 号空闲，5 号占用。"),
)

# 5、读出（conversation 按时间取最近 top_k 条，不靠语义搜索）
result = await memory.recall(memory_type="conversation", top_k=10)
```

| 调用                                                     | 作用                                                                         |
| -------------------------------------------------------- | ---------------------------------------------------------------------------- |
| `create_memory_manager(namespace=...)`                   | 为这个 id 准备记忆入口；`none` 表示本演示不做长期向量/图                     |
| `remember(..., memory_type="conversation", message=...)` | 把一条完整消息追加进**该 id** 的聊天流水（含 `tool_calls` / `tool_call_id`） |
| `recall(memory_type="conversation", top_k=...)`          | 读出该 id 下最近若干条消息                                                   |

### 你应在终端看到

（中间可能夹有 loguru 日志，关注打印块即可）

```text
【session_id / namespace】 demo-user-1
【召回条数】 4
【会话历史】
  [1] user: '帮我查一下 A 区柜子'
  [2] assistant: ''  | tool_calls=[call_api(...)]
  [3] tool: '[{"id": "3", ...}]'  | tool_call_id=call_list_1
  [4] assistant: 'A 区 3 号空闲，5 号占用。'
```

读法：在 `demo-user-1` 这个键下，工具回合也会整段落库；`recall` 按顺序带回。  
若把 `session_id` 改成 `demo-user-2` 再跑（或另起一个 manager），读到的是**另一本**空流水账——这就是上一节说的「换键即换绑」。

### 和真实对话的对应

| 测试里                     | Hubloom 对话里                                            |
| -------------------------- | --------------------------------------------------------- |
| 手写 `session_id`          | 请求传入的 `session_id`（Runtime 要求非空）               |
| 四次 `remember`（含 tool） | Agent 回合里落库用户话、助手 `tool_calls`、工具结果、终答 |
| `recall(conversation)`     | Think 拼上下文时取出近期历史（过长会裁剪）                |
| `vector/graph=none`        | 示例主路径常见装配：多轮靠会话层，长期检索另开            |

跑通这一段，你就已经摸到会话 Memory 的核心：**按隔离键写入消息 → 再按同一键读出来。** 长期记忆是否开启，不改变「键怎么绑」；只改变这个键下有没有额外的笔记库可搜。

---

## 长期记忆是什么？（接会话之后）

会话层解决的是：**这一条线里刚发生过什么**（逐条消息）。  
长期层解决的是：**这个隔离键下，哪些提炼过的事实 / 偏好 / 案例值得以后按需找回来**——不是把昨天聊天再整段塞进提示。

还用前面的外卖例子：通话录音是会话；店员笔记本上的「常客：少麻、多香菜」才是长期。  
查柜子同理：当天追问「那 3 号」靠会话历史；隔天再说「我一般先看 A 区」若要用上，靠的是笔记本里有没有沉淀过类似条目。

### 和会话记忆差在哪

|              | **会话（conversation）**                | **长期（episodic / semantic / …）**                                   |
| ------------ | --------------------------------------- | --------------------------------------------------------------------- |
| 存什么       | 用户 / 助手 / 工具的**原始消息**        | 提炼后的**笔记**：情景案例、稳定规则、可选实体关系                    |
| 何时写       | Agent 对话热路径里几乎每轮都 `remember` | 多半**事后巩固**（离线 worker），或显式写入；不是每条聊天都自动变笔记 |
| 怎么读       | 按时间取最近 `top_k` 条                 | 用 **query 做检索**（向量 / 关键词混合；图另算）                      |
| Hubloom 开关 | 几乎总有（数据会话库）                  | **可选**：`vector_backend` / `graph_backend`；示例主路径常为 `none`   |
| 依赖         | 本地SQLite或者其他数据库即可            | 开向量要 **Qdrant + embedder**；开图要 **Neo4j**                      |

隔离键不变：长期条目仍挂在同一个 `session_id` / `namespace` 下。换用户换键，搜到的也是另一本笔记本。

### Hubloom 里开了后端之后有三类

`create_memory_manager` 在 `vector_backend="qdrant"` 时挂上向量两路；`graph_backend="neo4j"` 时再挂图：

| `memory_type`   | 通俗理解       | 典型内容                                     |
| --------------- | -------------- | -------------------------------------------- |
| **episodic**    | 情景 / 案例    | 「某次交互里发生了什么」（可检索的经历摘要） |
| **semantic**    | 稳定语义       | 偏好、规则、可复用的事实归纳                 |
| **associative** | 联想图（可选） | 实体与关系；检索时常变成一段图摘要           |

关掉后端时（`none`）：这三类 handler 根本不装配——会话流水账仍在，只是没有长期检索库。

### 写入从哪来、读出怎么用

**写入（概念上）**

1. 对话仍先落在 **conversation**（上一节已经跑过）。
2. 需要长期沉淀时，常见路径是离线 **`memory_worker` / batch consolidator**：从会话里批量提炼成 episodic / semantic 等再写入向量库——**不在** Agent 每轮热路径里做重提炼。
3. 也可以对 `episodic` / `semantic` 等直接 `remember(content=...)`（接口支持）；最小演示见下一小节。

**读出（对话里怎么用到）**

- 不是 `recall(memory_type="conversation")` 那种按时间拉历史。
- 而是带着**当前问题**去搜，例如 Manager 的 `recall(query=..., mode="hybrid")`（合并 episodic + semantic），以及可选的 associative。
- Agent 侧常见消费方式：
  - 拼上下文时由 **`MemoryContextProvider`** 按 query 召回，规范化后交给 assembler；
  - 或模型调用工具 **`search_memory`**，按需再搜一轮。

一句话：

> **会话：按时间回放这条线刚聊过什么。**  
> **长期：按问题从笔记本里抽出几条相关笔记（可再加一点关系图）。**

### 最小动手：写入笔记再按 query 检索

完整对话里，长期笔记多半靠离线巩固写入，再由 `search_memory` / `MemoryContextProvider` 按问题召回。  
要先摸清「同一隔离键下笔记怎么写、怎么搜」，可以跑 [`tests/test_memory_longterm.py`](../../tests/test_memory_longterm.py)：手写两条笔记 + `hybrid` 检索，**不必起聊天服务**。

#### 前置：本地 Qdrant

长期向量依赖 Qdrant。可用 Docker 起本地实例（示例）：

```bash
docker run -d --name qdrant \
  -p 6333:6333 -p 6334:6334 \
  -v qdrant_storage:/qdrant/storage \
  qdrant/qdrant
```

在 `config/env.yaml` 里指向本地（Hubloom 目前仍要求填非空 `api_key`；本地默认不校验，可填占位）：

```yaml
qdrant:
  url: http://localhost:6333
  api_key: local-dev
  collection: hubloom_memory_local
```

Dashboard：http://localhost:6333/dashboard

本演示**不开** Neo4j。脚本会直接 `vector_backend="qdrant"`，不必把 `memory.enable_long_term` 设为 true。

#### 怎么跑

在**仓库根目录**执行：

```bash
PYTHONPATH=src .venv/bin/python tests/test_memory_longterm.py
```

#### 脚本在做什么

和会话脚本同形：**写入 → 读出**。差别是长期写的是笔记正文，读的时候带 **query**：

```python
session_id = "demo-user-1"
memory = create_memory_manager(
    namespace=session_id,
    vector_backend="qdrant",
    graph_backend="none",
    embedder=_DemoEmbedder(),  # 教学用本地假向量；生产换真实 Embedder
    ...
)

# 1、写入情景笔记
await memory.remember(
    memory_type="episodic",
    content="用户查询了 A 区柜子，得知 3 号空闲、5 号占用。",
)
# 2、写入语义笔记
await memory.remember(
    memory_type="semantic",
    content="用户偏好：查柜子时优先看 A 区。",
)
# 3、按问题混合检索（不是按时间拉聊天记录）
result = await memory.recall(
    query="用户查柜子时有什么偏好？",
    top_k=5,
    mode="hybrid",
)
```

| 调用                                                             | 作用                                      |
| ---------------------------------------------------------------- | ----------------------------------------- |
| `remember(..., memory_type="episodic"\|"semantic", content=...)` | 把一条笔记写入该 namespace 的向量库       |
| `recall(query=..., mode="hybrid")`                               | 按问题在 episodic + semantic 里检索并合并 |

演示脚本里还会把相似度门槛临时降到 `0.0`：假 embedder 分数偏低，若沿用生产默认 **0.55**，会出现「写成了、`recall` 却是 0」——这是演示妥协，不是生产推荐。

#### 你应在终端看到

（中间可能夹有 loguru 日志与 http 本地 api_key 警告，关注打印块即可）

```text
【session_id / namespace】 demo-user-1
【召回条数】 2
【长期记忆】
  [1] 用户查询了 A 区柜子，得知 3 号空闲、5 号占用。
  [2] 用户偏好：查柜子时优先看 A 区。
```

日志里还会看到类似 `hits=0.530:用户偏好…`：数字是相关度。  
读法：同一 `demo-user-1` 下先写后搜；命中的是**笔记**，不是会话逐字稿。脚本结束会 `clear_all`，避免污染本地 collection。

#### 和真实对话的对应

| 测试里                             | Hubloom 对话里                                           |
| ---------------------------------- | -------------------------------------------------------- |
| 手写 `session_id` / `namespace`    | 请求传入的 `session_id`                                  |
| 两次 `remember(content=...)`       | 离线巩固写入为主；也可显式写入                           |
| `recall(query=..., mode="hybrid")` | `MemoryContextProvider` / 工具 `search_memory`           |
| 假 embedder + 放宽门槛             | 生产用真实 embedding，保留默认相似度门槛                 |
| 本地 Docker Qdrant                 | 也可用 Qdrant Cloud；改 `env.yaml` 的 url / api_key 即可 |

部署与开关见进阶：[会话与记忆](../advanced/memory.md)（大纲可随后补正文）。  
巩固流水线（worker / consolidator）细讲可放下一轮。

---

## 设计怎么控？（结构 + 谁调用谁）

前面两节回答「存什么、怎么亲手写读」。这一节回答：**Hubloom 里 Memory 由谁装配、对话热路径写什么、长期从哪开、检索门槛在哪**。

### 分层：统一入口，按类型分派

```text
调用方（Runtime / Agent / Worker / 演示脚本）
        │
        ▼
create_memory_manager(...)     ← factory：按开关挂上哪些 Handler
        │
        ▼
MemoryManager                  ← 统一 remember / recall / clear_all
        │  按 memory_type 分派
        ├─ conversation  → ConversationHandler → SQLite
        ├─ episodic      → EpisodicQdrantHandler → Qdrant（需 vector）
        ├─ semantic      → SemanticQdrantHandler → Qdrant（需 vector）
        └─ associative   → AssociativeHandler   → Neo4j（需 graph）
```

要点：

- **对外只认 Manager**：业务代码一般不直接碰 Store。
- **类型决定参数**：`conversation` 传 `message=`；长期传 `content=`（associative 还可带关系 metadata）。
- **没挂上的类型会报错**：`vector_backend="none"` 时没有 episodic/semantic handler；不是「空库」，是根本没装配。

相关文件：

| 角色           | 路径                                                                                      |
| -------------- | ----------------------------------------------------------------------------------------- |
| 工厂           | `src/memory/factory.py`                                                                   |
| 统一入口       | `src/memory/manager.py`                                                                   |
| 各类型 Handler | `src/memory/handlers/`                                                                    |
| 存储           | `src/memory/store/`（SQLite / Qdrant / Neo4j）                                            |
| 会话拼进提示   | `src/agent/assemble.py`（`load_conversation`）                                            |
| 长期检索适配   | `src/memory/memory_context.py` + 工具 `SearchMemoryTool`                                  |
| 离线巩固       | `src/memory/memory_worker.py`、`batch_consolidator.py`；CLI `python -m memory.run_worker` |

### 两路控制：对话热路径 vs 离线巩固

|                | **热路径（一次 `run_stream`）**                                     | **离线（cron / CLI worker）**                |
| -------------- | ------------------------------------------------------------------- | -------------------------------------------- |
| 谁触发         | `HubloomRuntime` → `agent.run`                                      | `memory.run_worker`                          |
| 主要写什么     | **几乎只写 conversation**（用户 / 助手 / 工具消息）                 | 从会话提炼 **episodic / semantic**（可选图） |
| 主要读什么     | `assemble.load_conversation`：按时间取最近历史并裁剪                | 不服务当前用户请求；写完供以后检索           |
| 长期怎么进对话 | 工具 **`search_memory`**（底层 `MemoryContextProvider`）按 query 搜 | —                                            |

热路径里会话的控制很直接：

1. Runtime 用 `session_id` 调 `create_memory_manager(namespace=session_id, ...)`
2. Agent 回合里 `_remember(...)` → `memory.remember(memory_type="conversation", message=...)`
3. 拼 Think / Respond 前 `load_conversation` → `recall(memory_type="conversation")`，过长再 `trim_conversation_history`

长期**不会**在每轮 Think 里自动把全库笔记塞进提示；需要时由模型调 `search_memory`，或由上层显式走 `MemoryContextProvider`。

### 开关与装配：谁决定「有没有长期」

配置（`config/env.yaml`）里常见旋钮：

| 配置                           | 作用                                                                 |
| ------------------------------ | -------------------------------------------------------------------- |
| `memory.db_path`               | 会话 SQLite 路径（会话层几乎总开）                                   |
| `memory.enable_long_term`      | 给 **Worker** 等读：是否按长期后端去提炼 / 淘汰                      |
| `memory.consolidate_min_turns` | 未处理 USER 轮数达到该值才巩固                                       |
| `qdrant.*` / `neo4j.*`         | 向量库 / 图库连接                                                    |
| `llm.*`                        | 巩固用 LLM；真实 embedding 也常用同一套 key（网关需支持 embeddings） |

工厂参数与配置的对应：

- `vector_backend="qdrant"` → 挂 episodic + semantic
- `graph_backend="neo4j"` → 挂 associative
- `"none"` → 不挂对应 Handler

**当前 Runtime 装配要注意的一点**：`HubloomRuntime._make_memory` 里目前**写死** `vector_backend="none"`、`graph_backend="none"`——也就是说：

- 线上对话主路径默认仍是 **只开会话 SQLite**；
- 仍会注册 `SearchMemoryTool`，但 Manager 上没有长期 Handler 时，搜长期会失败或空；
- 长期写入 / 检索要靠：**演示脚本那种显式开 qdrant**，或 **Worker 用 `enable_long_term` 装配**，或以后把 Runtime 的 `_make_memory` 接到配置上。

这是「控制」上很关键的现状：配置里的 `enable_long_term` **主要驱动离线 Worker**，并不等于「对话 Runtime 已自动连上 Qdrant」。

### 检索与淘汰：质量旋钮

| 旋钮                                 | 在哪                                                       | 作用                                                           |
| ------------------------------------ | ---------------------------------------------------------- | -------------------------------------------------------------- |
| `mode=hybrid` / 单路 `memory_type`   | `MemoryManager.recall`                                     | hybrid 合并 episodic+semantic；conversation / associative 另走 |
| `top_k`                              | recall / SearchMemoryTool                                  | 最多返回条数                                                   |
| `score_threshold`（默认约 **0.55**） | Qdrant Handler / Store                                     | 相似度低于门槛的命中直接丢掉                                   |
| TTL / 容量                           | `lifecycle` + Worker `run_maintenance`                     | 长期条目过期或超额淘汰                                         |
| 会话 `top_k` + token 裁剪            | `assemble.load_conversation` / `trim_conversation_history` | 防止历史把上下文撑爆                                           |

教学脚本里把门槛降到 `0.0`，只为假 embedder 能演示「搜得到」；生产应保留门槛 + 真实 embedding。

### 一张总图（控制流）

```text
请求 session_id
    │
    ├─ Runtime._make_memory(session_id)
    │       └─ 当前：仅 conversation（vector/graph=none）
    │
    ├─ Agent 热路径
    │       ├─ remember(conversation)  ← 每轮消息
    │       ├─ recall(conversation)    ← 拼上下文
    │       └─（可选）search_memory   ← 模型主动搜长期
    │
    └─ 离线 Worker（enable_long_term + qdrant…）
            ├─ 读 SQLite 会话，满 N 轮则 LLM 提炼
            ├─ remember(episodic/semantic/…)
            └─ run_maintenance 淘汰
```

读完这一节，你应能回答：

1. **谁统一对外？** `MemoryManager`。
2. **对话默认控什么？** 会话写入与按时间召回；长期默认未接到 Runtime。
3. **长期谁打开？** factory 的 backend 开关 +（现状下）Worker / 显式脚本。
4. **搜不到可能是？** 没装配 Handler、门槛过滤、或 embedder/query 不匹配——不一定是「没写入」。
