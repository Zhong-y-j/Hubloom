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

## 设计细节：如何存、如何读、如何控

前面两节回答「存什么、怎么亲手写读」。这一节按实现讲清：**会话行怎么落库、长期笔记怎么进向量库、读的时候各走哪条路、谁在控制开关与裁剪**。

### 总原则

Memory **不是**一套库两种用法，而是 **统一 Manager + 多种 Handler**：

| 类型 | 存什么 | 怎么读 | 后端 |
| --- | --- | --- | --- |
| `conversation` | 完整 `Message`（含 tool） | **按时间**最近 N 条 | SQLite |
| `episodic` / `semantic` | 笔记 `content` + 向量 | **按 query 向量检索** | Qdrant |
| `associative` | 实体 / 关系 | **图邻域** | Neo4j（可选） |

和 RAG 的对比（避免混）：

| | Memory 会话 | Memory 长期 | RAG |
| --- | --- | --- | --- |
| 切块 / 分词？ | 不切；一条消息一行 | 不切文档；一条笔记一条向量 | 文档切块 + Token 估算 |
| 隔离 | `session_id` | 同键作 `namespace` | 通常共享文档库 |
| 主读法 | 时间序 | 相似度 | 相似度 |

### 分层：统一入口，按类型分派

```text
调用方（Runtime / Agent / Worker / 演示脚本）
        │
        ▼
create_memory_manager(...)     ← factory：按开关挂上哪些 Handler
        │
        ▼
MemoryManager                  ← 统一 remember / recall / clear_all / forget
        │  按 memory_type 分派
        ├─ conversation  → ConversationHandler → SQLite
        ├─ episodic      → EpisodicQdrantHandler → Qdrant（需 vector）
        ├─ semantic      → SemanticQdrantHandler → Qdrant（需 vector）
        └─ associative   → AssociativeHandler   → Neo4j（需 graph）
```

要点：

- **对外只认 Manager**；业务一般不直接碰 Store。
- **类型决定参数**：`conversation` 必须 `message=`；长期必须 `content=`。
- **没挂上的类型会报错**：`vector_backend="none"` 时没有 episodic handler——不是「空库」，是根本没装配。

相关文件：

| 角色 | 路径 |
| --- | --- |
| 工厂 | `src/memory/factory.py` |
| 统一入口 | `src/memory/manager.py` |
| Handler | `src/memory/handlers/` |
| Store | `src/memory/store/`（SQLite / Qdrant / Neo4j） |
| 会话拼进提示 | `src/agent/assemble.py`、`memory/context.py`（裁剪） |
| 长期检索适配 | `src/memory/memory_context.py` + `SearchMemoryTool` |
| 生命周期 | `src/memory/lifecycle.py` |
| 离线巩固 | `memory_worker.py`、`batch_consolidator.py`；`python -m memory.run_worker` |

---

### 如何存

#### 会话（conversation → SQLite）

热路径几乎每轮：`memory.remember(memory_type="conversation", message=...)`  
→ `ConversationHandler.append` → `ConversationSQLitesStore.add_message`。

表 `conversation_memory` 核心列：

| 列 | 含义 |
| --- | --- |
| `id` | 消息主键 |
| `session_id` | 隔离键（= Runtime 的 `session_id`） |
| `role` / `content` | 角色与正文 |
| `tool_calls` | JSON：助手发起的工具调用列表 |
| `tool_call_id` / `name` | 工具回传时对齐某次 call |
| `created_at` | 时间（取最近 N 条的排序依据） |
| `metadata_json` / `source` / `token_count` / `turn_index` | 扩展；巩固定位 turn 会用到 id |

设计选择：

- **整条 Message 落库**（含 tool 过程），拼上下文时才能还原工具回合。
- **不做向量、不做分词检索**；会话层就是流水账。
- 索引：`(session_id, created_at)`，按会话取最近消息。
- Handler 层 **不提供单条 forget**（`forget` 恒为 false）；清空用 `clear_all`。
- 存储层不做会话 TTL——**过长历史靠组装时 trim**，不靠删库。

#### 长期（episodic / semantic → Qdrant）

`remember(memory_type="episodic"|"semantic", content=...)`  
→ Handler：`embedder.embed([content])` → 组装 Item → `QdrantMemoryStore` upsert。

常见字段：

| 字段 | 含义 |
| --- | --- |
| `content` | 笔记正文（检索主文本） |
| `namespace` | 隔离键（与 session 同值装配） |
| `memory_type` | collection 内区分 episodic / semantic |
| embedding | 向量（写入时算好） |
| `importance` / `ref_session_id` | 可选；淘汰与溯源 |
| `created_at` / `last_accessed_at` | TTL / 维护用 |

写入来源：

1. **演示 / 显式 API**：手写 `remember(content=...)`
2. **离线 Worker**：读 SQLite 会话 → LLM 提炼 → 再 `remember` 长期类型（主生产路径）

**Associative（可选）**：`remember` + metadata（`from_name`/`to_name` 建关系，或挂 MemoryRef 指向向量记忆 id）；存在 Neo4j。

---

### 如何读

#### 会话：按时间，不是按问题

```text
recall(memory_type="conversation", top_k=N)
  → store.get_recent(session_id, N)
  → ORDER BY created_at DESC LIMIT N，再反转为时间正序
  → list[Message]
```

`query` / `mode` 在 Handler 里预留，**当前忽略**。

进提示词之前还有第二道闸：

```text
assemble.load_conversation(top_k=…)
  → trim_conversation_history(messages, max_tokens=…)
```

`trim_conversation_history`（`memory/context.py`）按**估算 token**裁掉偏旧内容，尽量保留较新回合。  
注意：**裁剪发生在组装层，不删除 SQLite 里的历史。**

#### 长期：按 query 向量检索

```text
# 单路
recall(memory_type="episodic"|"semantic", query=..., top_k=...)

# 多路（默认）
recall(query=..., mode="hybrid", top_k=...)
  → 分别搜 episodic + semantic → Manager 去重后截断到 top_k

# 图
recall(memory_type="associative", query=..., filters={hops, ...})
  → 结果在 RecallResult.graph
```

Handler：`embed(query)` → Qdrant search → 带 `metadata["score"]` 的条目。  
默认 **`score_threshold ≈ 0.55`**：低于门槛直接丢弃（「写成了但搜不到」的常见原因）。

对话里常见消费：

- **`SearchMemoryTool`** → `MemoryContextProvider.recall_for_context(query)`（hybrid + 可选图摘要）
- 或上层显式调 Provider / Manager（当前 Runtime 未自动把长期预取进每轮 system）

---

### 如何控（开关、两路、淘汰）

#### 两路：热路径 vs 离线

| | **热路径（`run_stream`）** | **离线（`run_worker`）** |
| --- | --- | --- |
| 谁触发 | Runtime → Agent | cron / CLI |
| 主要写 | **conversation** | 提炼后的 **episodic / semantic**（可选图） |
| 主要读 | 时间序会话 + trim | 不服务当次用户请求 |
| 长期进对话 | 模型调 `search_memory`（需 Handler 已装配） | — |

热路径会话三步：

1. `_make_memory(session_id)` → `create_memory_manager(namespace=session_id, …)`
2. `_remember` → `remember(conversation, message=…)`
3. `load_conversation` → `recall(conversation)` → trim → 拼 Think/Respond

长期**不会**每轮自动灌进提示；要搜才搜。

#### 配置与工厂

| 配置 | 作用 |
| --- | --- |
| `memory.db_path` | 会话 SQLite 路径（几乎总开） |
| `memory.enable_long_term` | **Worker** 是否按长期后端提炼 / 淘汰 |
| `memory.consolidate_min_turns` | 未处理 USER 轮数 ≥ N 才巩固 |
| `qdrant.*` / `neo4j.*` | 向量 / 图连接 |
| `llm.*` | 巩固用 LLM；真实 embedding 常用同一套（需 embeddings 能力） |

工厂：

- `vector_backend="qdrant"` → 挂 episodic + semantic
- `graph_backend="neo4j"` → 挂 associative
- `"none"` → 不挂

**现状（重要）**：`HubloomRuntime._make_memory` **写死** `vector/graph=none`。

- 对话主路径默认 **只有会话 SQLite**；
- 仍可能注册 `SearchMemoryTool`，但没有长期 Handler 时搜不到；
- `enable_long_term` **主要驱动 Worker**，≠「Runtime 已连上 Qdrant」；
- 要联调长期：演示脚本显式开 qdrant，或跑 Worker，或以后把 Runtime 接到配置。

#### 质量与淘汰旋钮

| 旋钮 | 在哪 | 作用 |
| --- | --- | --- |
| `top_k` | recall / 工具 / `load_conversation` | 条数上限 |
| 会话 token 预算 | `trim_conversation_history` / ContextAssembler | 组装时裁历史 |
| `mode=hybrid` 等 | `MemoryManager.recall` | 长期多路怎么合 |
| `score_threshold`（≈0.55） | Qdrant Handler | 过滤低相关命中 |
| TTL / `max_items` | `TTLBasedPolicy`（默认约 30 天 / 1000 条）+ `run_maintenance` | 长期过期或超额淘汰 |
| `importance` | 长期 metadata | 策略层可优先保留 |

会话 Handler 的 `run_maintenance` **故意返回 0**：会话不靠存储 TTL 删，靠组装裁剪。

教学脚本把长期门槛降到 `0.0` 只为假 embedder；生产应保留门槛 + 真实 embedding。

#### 总控制流

```text
请求 session_id
    │
    ├─ Runtime._make_memory(session_id)
    │       └─ 当前：仅 conversation（vector/graph=none）
    │
    ├─ Agent 热路径
    │       ├─ remember(conversation)     ← 每轮消息整行落 SQLite
    │       ├─ recall(conversation)+trim  ← 按时间取最近，再按 token 裁
    │       └─（可选）search_memory       ← query 搜长期（需已装配）
    │
    └─ 离线 Worker（enable_long_term + qdrant…）
            ├─ 读 SQLite，满 N 轮 USER → LLM 提炼
            ├─ remember(episodic/semantic/…)
            └─ run_maintenance（TTL / 容量）
```

---

读完「设计细节」你应能回答：

1. **谁统一对外？** `MemoryManager`；按 `memory_type` 分派。
2. **会话如何存 / 读？** SQLite 整行 Message；按时间 `get_recent`，组装再 trim。
3. **长期如何存 / 读？** content→embedding→Qdrant；按 query 检索 + 分数门槛。
4. **对话默认控什么？** 会话读写；长期默认未接到 Runtime。
5. **长期谁打开？** factory backend +（现状）Worker / 显式脚本。
6. **搜不到可能是？** 没装配 Handler、门槛过滤、embedder/query 不匹配——不一定没写入。
