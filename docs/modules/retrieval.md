# Retrieval（RAG）

## Retrieval 介绍

大模型上下文里**通常没有**你的产品手册、制度条文、内部说明。用户问「Hubloom 是什么」「柜子编号规则写在哪」时，若不加约束，模型容易用通用知识瞎猜，甚至编造。  
**Retrieval / RAG（检索增强生成）**要解决的，就是先把外部文档切块、向量化放进知识库；提问时按问题**检索相关片段**，再交给模型结合这些片段作答——让回答有据可查，而不是凭空发挥。

可以把它想成：柜台上永远摊着一本《菜单 / 产品手册》。客人问规格，店员先翻到相关页再回答；这和「记得住刚才那通电话说了什么」（会话 Memory）、以及「笔记本上写着常客偏好」（长期 Memory）不是同一件事。实时状态——「A 区 3 号现在空闲吗」——更适合调业务 API，手册未必有此刻数据。

和邻近概念的分界：

- **会话记忆**：这一条对话线里刚发生过什么
- **长期记忆**：这个用户名下提炼过的偏好 / 事实（按 session 隔离）
- **RAG**：共享（或项目级）文档知识库里有什么
- **MCP / API**：业务系统此刻的状态与操作

一句话：  
**RAG 管「文档知识库里有什么、怎么搜出来」；不管聊天记录，也不管业务接口怎么调。**

在 Hubloom 里，入库大致是「文件 → 转成 Markdown → 按结构切块 → embedding → 写入 Chroma」；提问则是「query →（可选改写）→ embedding → 向量 Top-K → 片段交给模型」。核心类型是 `KnowledgeBase`。模块与 `search_documents` 工具已写好，但当前 `HubloomRuntime` 主路径**尚未默认挂载**——学管线可跑演示脚本；要让在线 Agent 真会搜文档，还需后续装配。

读完上面，你应能分清 RAG 与 Memory / API、以及「先检索再生成」在解决什么问题。下一节讲设计取舍；再往后是动手与实现地图。

---

## 设计思路

介绍里说的是「要解决什么」。这一节说的是：**为什么建成现在这样，而不是另一种样子**。

### 1. 向量 RAG，而不是分词倒排当主检索

也可以走 jieba 一类分词 + 倒排索引。Hubloom 选择的主路径是：文本切块 → embedding → 相似度检索。中英混合、语义相近但用词不同的问法，更适合向量；Token 估算只用来**控块大小**，不参与匹配。  
代价是依赖 embedder 质量，且入库与检索必须同一套模型与维度，否则分数无意义。

### 2. 先统一成 Markdown，再按标题结构切块

PDF / docx / md 格式各异。先用 Loader（MarkItDown 等）收成一份 Markdown，后面切块只认「带结构的文本」，避免为每种格式写一套切法。  
切块优先按标题分 section，再在 section 内按 Token 上限切，并给块加上 `section_path` 前缀、保留 overlap、合并过短块——让命中片段可读、少碎、边界不那么脆。不是「整篇塞进一个向量」，也不是「无视结构均匀切字」。

### 3. 知识库默认共享，与 Memory 分库

产品手册通常是团队共用，不是「每个 session 一本手册」。因此 RAG 默认不按 `session_id` 隔离；长期 Memory 才按 namespace 分户。  
后端也分开：RAG 用本地 Chroma（目录持久化，演示友好）；长期 Memory 常用 Qdrant。工具分别是 `search_documents` 与 `search_memory`，避免一个库里既塞聊天笔记又塞制度全文。

### 4. 入库与检索共用 Embedder；查询优化可选、默认关掉

生产用真实 `OpenAIEmbedder`（或同类）；演示可用假向量——分数别当真。  
HyDE / MQE 等查询优化能改善抽象题或模糊题，但依赖额外 LLM 调用，所以默认 `optimize=none`；需要时再挂 `QueryOptimizer`。未挂优化器时传 hyde/mqe 也会退回直接检索。

### 5. 模块先完备，Runtime 装配后置

能力（KB、切块、工具类）可以先在仓库里跑通；对话主路径是否挂载是产品开关与装配问题。当前与长期记忆类似：**模块可用，Runtime 默认未接**。这样学模块不必等整站装配；上线时再 `create_knowledge_base` + 注册 `search_documents`。

### 6. 批量入库按文件名跳过，避免重复索引

`ingest_rag_sources` 若发现同名 `doc_name` 已在库中则跳过。这是工程上的省事默认，不是内容哈希去重——改了文件内容但文件名不变时，需要自行删旧再入或换策略。

一句话对照：

| 若做成…                 | 我们选择…               | 主要理由               |
| ----------------------- | ----------------------- | ---------------------- |
| 分词倒排做主检索        | 向量相似度 Top-K        | 语义召回、中英混合更稳 |
| 按格式各写切块器        | 先 Markdown 再结构切块  | 管线单一               |
| 每用户一本手册库        | 默认共享知识库          | 文档生命周期不同       |
| 与长期记忆同一后端      | Chroma vs Qdrant 等分库 | 隔离语义清晰           |
| 默认 HyDE/MQE           | 默认直接搜，优化可选    | 控成本与复杂度         |
| 等 Runtime 挂好再写模块 | 模块先完备 + 演示脚本   | 可独立验证             |

---

## 本章怎么读

1. **落地速览**：管线、配置、装配现状（紧接下一节）
2. **动手**：[`tests/test_retrieval.py`](../../tests/test_retrieval.py)（临时 Chroma + 假 embedder，不必起聊天服务）
3. **设计细节**：如何存 / 切 / 读
4. **设计怎么控**：目录职责与控制流

---

## 落地速览

```text
文档文件（md / pdf / …）
    → DocumentLoader（转成 Markdown）
    → SemanticSplitter（按结构切块）
    → Embedder（文本 → 向量）
    → ChromaDB（文本 + 向量 + 元数据）

提问 query
    → Embedder（可选 QueryOptimizer）
    → Chroma 向量检索
    → [{text, metadata, score}, ...]
    →（目标）工具 search_documents → 模型作答
```

核心类型：`KnowledgeBase`（`add_document` / `search` / `clear`）。工厂：`create_knowledge_base` / `ingest_rag_sources`（`src/retrieval/rag_bootstrap.py`）。

|            | Memory 长期                   | Retrieval                  |
| ---------- | ----------------------------- | -------------------------- |
| 存什么     | 对话提炼出的笔记              | 外部文档切块               |
| 默认后端   | Qdrant（可选）                | **Chroma**（本地目录）     |
| Agent 工具 | `search_memory`               | `search_documents`         |
| 隔离       | 按 `session_id` / `namespace` | 知识库通常是**共享文档库** |

`config/env.yaml`：

```yaml
rag:
  enable: false
  kb_dir: data/knowledge_db
  docs: '' # 逗号分隔的文件或目录；相对仓库根
```

| 配置         | 作用                                            |
| ------------ | ----------------------------------------------- |
| `rag.enable` | 是否启用（与 `docs` 组合，见 `is_rag_enabled`） |
| `rag.kb_dir` | Chroma 持久化目录                               |
| `rag.docs`   | 启动时要入库的文档路径                          |
| `llm.*`      | 生产给真实 Embedder（及可选查询优化 LLM）用     |

**现状**：模块与工具类已就绪；`HubloomRuntime` 主路径尚未挂载 KB / `search_documents`。学管线跑演示脚本即可；在线 Agent 要会搜文档，需后续装配。

---

## 最小动手：入库再检索

脚本：[tests/test_retrieval.py](../../tests/test_retrieval.py)。  
用临时 Chroma + 本地假 embedder，**不必**起聊天服务，也**不必** Qdrant。

### 怎么跑

在**仓库根目录**：

```bash
PYTHONPATH=src .venv/bin/python tests/test_retrieval.py
```

### 脚本在做什么

```python
kb = create_knowledge_base(
    persist_dir=...,           # 临时 Chroma 目录
    embedder=_DemoEmbedder(),  # 教学用；生产换真实 Embedder
)

# 1、入库
doc_id = await kb.add_document("docs/README.md")

# 2、按问题检索（optimize=none：不做 HyDE / MQE）
hits = await kb.search("介绍一下Hubloom", top_k=3, optimize="none")
```

| 调用                         | 作用                          |
| ---------------------------- | ----------------------------- |
| `create_knowledge_base(...)` | 建知识库（Chroma + embedder） |
| `add_document(path)`         | 加载 → 切块 → 向量化 → 写入   |
| `search(query, top_k=...)`   | 按问题返回相关片段            |

### 你应在终端看到

```text
【文档】 README.md doc_id= ...
【查询】 介绍一下Hubloom
【命中条数】 3
【检索结果】
  [1] score=... section='Hubloom 文档'
      Hubloom ... 基座脚手架 ...
  ...
```

读法：

- **流程正常**：有入库 chunks、有命中条数、正文和问题相关 → 管线通了。
- **分数别当真**：假 embedder 下 `score` 可能为负或乱序感强；换真实 embedding 后才有参考价值。
- 脚本结束会 `kb.clear()`，避免演示污染目录。

---

## 设计细节：如何存、如何切、如何读

前面是介绍、设计思路与落地/动手。这一节按实现讲清：**一片文档进库时发生了什么、块怎么切、检索时怎么拿回来**。  
代码主战场：`KnowledgeBase` + `SemanticSplitter` + `Embedder` + Chroma。

### 总原则

Hubloom RAG **不是**「整篇文档塞进向量库再全文关键词搜」，也**不是**经典 NLP 里先做中文分词（jieba 一类）再建倒排索引。

设计选择是：

1. **统一成 Markdown 文本**（方便按标题结构理解）；
2. **按语义结构切块**（标题路径 + Token 上限 + 重叠）；
3. **每块各算一条向量**，和正文、元数据一起写入 Chroma；
4. **提问也变成向量**，用相似度取 Top-K 块。

「Token」在切块里是**估算量**（控制块别太大），不是检索用的分词结果。

### 如何存（入库）

`KnowledgeBase.add_document(file_path)` 固定五步：

```text
file
  → ① Loader：变成一份 Markdown 字符串
  → ② Splitter：变成若干 { content, metadata }
  → ③ Embedder：对每个 content 算 embedding（可分批，默认 batch=8）
  → ④ 组装 Chroma 行：id / document / embedding / metadata
  → ⑤ collection.add(...)
```

**① 加载（`DocumentLoader`）**

| 类型                        | 策略                              |
| --------------------------- | --------------------------------- |
| 代码后缀（`.py` 等）        | 读原文，包成 Markdown 代码块      |
| 其它（`.md` / pdf / docx…） | **MarkItDown** 转成 Markdown 正文 |

目的：后面切块只认「带标题的文本」，不认每种二进制格式。

**② 切块** → 见下一小节 `SemanticSplitter`。

**③ 向量**

- 接口：`Embedder.embed(list[str]) → list[list[float]]`
- 生产常用 `OpenAIEmbedder`；演示可用本地假实现。
- **入库与检索必须用同一套 embedder / 维度**，否则相似度无意义。

**④⑤ 落库（Chroma 里一行 ≈ 一块）**

| 字段         | 含义                               |
| ------------ | ---------------------------------- |
| `id`         | `{doc_id}_{chunk_id}`，全局唯一    |
| `documents`  | 块正文（常已带上「标题路径」前缀） |
| `embeddings` | 该正文对应向量                     |
| `metadatas`  | 切块元数据 + 文档级字段            |

文档级会并进 metadata 的常见键：

| 键                                          | 含义                                           |
| ------------------------------------------- | ---------------------------------------------- |
| `doc_id`                                    | 本次入库生成的文档 ID                          |
| `doc_name`                                  | 文件名（批量入库时用它跳过「已索引同名文件」） |
| `source_type`                               | 扩展名，如 `.md`                               |
| `indexed_at`                                | 入库时间                                       |
| `chunk_id` / `chunk_index` / `total_chunks` | 块编号                                         |
| `section_path` / `heading`                  | 章节路径，方便展示与溯源                       |
| `prev_chunk_id` / `next_chunk_id`           | 邻块指针（元数据关联；检索默认不自动拼邻块）   |

删除：`delete_document(doc_id)` 按 metadata 里的 `doc_id` 删该文档全部块。  
清空：`clear()` 删 collection 再建空的。

批量入口 `ingest_rag_sources`：展开目录 → 若 `doc_name` 已在库中则**跳过**，避免重复索引同名文件。

### 如何切（切片设计，不是分词索引）

实现：`SemanticSplitter`（`semantic_splitter.py`）。

默认旋钮：

| 参数                   | 默认 | 作用                                   |
| ---------------------- | ---- | -------------------------------------- |
| `chunk_token_size`     | 384  | 单块目标上限（估算 Token）             |
| `overlap_token_size`   | 64   | 与上一块尾部重叠，减轻「答案卡在边界」 |
| `min_chunk_token_size` | 100  | 过短块会并进前一块                     |
| `max_heading_chars`    | 40   | 过长行不当中文编号标题，防误判         |

#### 切块流水线

```text
Markdown 文本
  → 识别标题（# 标题 优先；其次「一、」「（一）」「第一章」等）
  → 解析成 section 列表（每个 section：level / heading / path / 直属正文）
  → 每个 section 内按 Token 上限再切（优先段落 \n\n，再句子。！？等）
  → 块正文前缀加上 section_path（如「Hubloom 文档 > 从哪开始读？」）
  → 合并过短块 + 加 overlap
  → 输出 [{ content, metadata }, ...]
```

无标题时走 **`_split_flat_text`**：只按段落 / 句子聚合到 Token 上限，`section_path` 为空。

#### 「Token」怎么估（不是分词器）

`_estimate_tokens` 是启发式：

- 中文字符 ≈ 0.7 token/字
- 英文单词 ≈ 1.3 token/词
- 数字串 ≈ 1 token/组

用来**控块大小**，不参与检索匹配。检索靠的是 embedding 相似度。

#### 为什么这样设计

| 选择                  | 理由                                               |
| --------------------- | -------------------------------------------------- |
| 先按标题再切          | 块尽量落在同一小节，检索命中后 `section_path` 可读 |
| 路径写进 content 前缀 | 向量里也带上「这是哪一节」，减少裸段落丢上下文     |
| overlap               | 跨段句子被切开时，邻块仍有一点共享上下文           |
| 合并过短块            | 避免大量碎片噪声                                   |
| 不用分词倒排做主检索  | 与向量 RAG 路线一致；中英混合用估算即可控尺寸      |

你在演示里看到 `chunks=5`，就是这篇 Markdown 被切成 5 个带 metadata 的块后再分别 embedding。

### 如何读（检索）

`KnowledgeBase.search(query, top_k=..., optimize=..., where=...)`：

```text
query
  →（可选）QueryOptimizer：hyde / mqe 改写或扩写
  → embedder.embed([用于检索的文本])
  → collection.query(query_embeddings=..., n_results=top_k, where=...)
  → 每条整理为 { id, text, metadata, score }
```

**分数**：实现里 `score = 1.0 - distance`（Chroma 返回的 distance）。  
真实 embedding 下，越大通常越相关；假 embedder 下可能出现负数——只说明距离换算后的数，不代表质量。

**`where`**：可按 Chroma metadata 过滤（例如只搜某个 `doc_id`）；工具默认一般不传。

**工具层** `SearchDocumentsTool`：把命中格式化成「来源 / 章节 / 相关度 + 正文」字符串给模型；`optimize` 参数透传。

### 可选查询优化（读路径上的增强）

| `optimize` | 行为                               | 适合        |
| ---------- | ---------------------------------- | ----------- |
| `none`     | 原问题直接搜                       | 默认、演示  |
| `hyde`     | LLM 先写假设答案，用答案向量去搜   | 抽象/概括题 |
| `mqe`      | LLM 改成多个问法，并行搜再去重排序 | 模糊/开放题 |

需要构造 `KnowledgeBase(..., query_optimizer=QueryOptimizer(llm))`；未挂优化器时即使传 hyde/mqe 也会退回直接检索。

---

## 设计怎么控？（结构 + 谁调用谁）

### 目录与职责

| 路径                              | 职责                                  |
| --------------------------------- | ------------------------------------- |
| `retrieval/rag_bootstrap.py`      | 开关判断、路径解析、创建 KB、批量入库 |
| `retrieval/knowledge_base.py`     | 入库 / 检索 / 删除 / 清空（Chroma）   |
| `retrieval/loader.py`             | 多格式 → Markdown（MarkItDown）       |
| `retrieval/semantic_splitter.py`  | 结构感知切块 + Token 估算 + 重叠      |
| `retrieval/query_optimizer.py`    | 可选：HyDE / MQE（要 LLM）            |
| `embedders/`                      | 向量化抽象；默认实现 `OpenAIEmbedder` |
| `tools/builtin/retrieval_tool.py` | Agent 工具 `search_documents`         |

### 控制流（装配视角）

```text
（演示 / 未来 Runtime 启动）
    create_knowledge_base(persist_dir, embedder)
    ingest_rag_sources(kb, docs) 或 kb.add_document(path)
            │
            ├─ loader.load
            ├─ splitter.split
            ├─ embedder.embed
            └─ chroma.add

（提问）
    kb.search(query) 或 SearchDocumentsTool.execute(query)
            ├─（可选）QueryOptimizer：hyde / mqe
            ├─ embedder.embed(query)
            └─ chroma.query → [{text, metadata, score}, ...]
```

### 和 Agent 的关系（目标形态）

```text
用户问文档类问题
    → 模型调用 search_documents
    → KnowledgeBase.search
    → 片段回工具结果
    → 模型据此回答
```

当前 Runtime 尚未自动走通上图；模块本身已按此设计。

读完「设计细节 + 本节约」你应能回答：

1. **存什么？** 每块：正文 + 向量 + 元数据（含 `doc_id`、章节路径）。
2. **怎么切？** 标题结构 → Token 上限 → 重叠；Token 是估算，不是分词索引。
3. **怎么读？** query（可选优化）→ 向量 → Top-K；`score≈1-distance`。
4. **和 Memory？** 文档共享库 vs 按 session 的聊天/笔记。
5. **对话里？** 目标工具 `search_documents`；Runtime 装配仍待接。
