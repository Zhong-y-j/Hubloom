# Retrieval（RAG）

## Retrieval 是什么？

**Retrieval / RAG（检索增强生成）**解决的是：模型上下文里**没有**你的产品手册、制度、内部说明时，回答容易瞎编。做法是：先把外部文档切块、向量化存进知识库；提问时按问题**检索相关片段**，再交给模型结合这些片段作答。

一句话：

> **RAG 管「文档知识库里有什么、怎么搜出来」；不管聊天记录，也不管业务接口怎么调。**

---

## 用例子建立感觉

假设用户问：「Hubloom 是什么？」

| 做法                        | 会发生什么                                                           |
| --------------------------- | -------------------------------------------------------------------- |
| 不靠文档                    | 模型可能用通用知识猜，或编造                                         |
| 有 RAG                      | 先从 `docs/README.md` 等手册里搜到「基座脚手架」片段，再基于片段回答 |
| 问「A 区 3 号现在空闲吗？」 | 更适合 **MCP 调业务 API**；手册未必有实时状态                        |

对照 Memory：

| 用户问题                        | 主要靠什么             |
| ------------------------------- | ---------------------- |
| 「刚才那个柜子」                | **会话记忆**           |
| 「我一般先看 A 区」（隔天偏好） | **长期记忆**（若开启） |
| 「产品手册里柜子编号规则」      | **RAG**                |
| 「现在帮我占用 3 号」           | **MCP / API**          |

---

## 在 Hubloom 里怎么落地？

### 管线（入库 → 检索）

```text
文档文件（md / pdf / …）
    → DocumentLoader（MarkItDown 等转成 Markdown）
    → SemanticSplitter（按结构切块）
    → Embedder（文本 → 向量）
    → ChromaDB（本地持久化：文本 + 向量 + 元数据）

提问 query
    → Embedder
    → Chroma 向量检索
    → 返回若干 {text, metadata, score}
    →（对话里）常经工具 search_documents 交给模型
```

核心类型是 **`KnowledgeBase`**（`src/retrieval/knowledge_base.py`）：负责 `add_document` / `search` / `clear`。

### 和 Memory 的差别（别混库）

|            | Memory 长期                   | Retrieval                                          |
| ---------- | ----------------------------- | -------------------------------------------------- |
| 存什么     | 对话提炼出的笔记              | 外部文档切块                                       |
| 默认后端   | Qdrant（可选）                | **Chroma**（本地目录）                             |
| Agent 工具 | `search_memory`               | `search_documents`                                 |
| 隔离       | 按 `session_id` / `namespace` | 知识库通常是**共享文档库**（不按用户各备一本手册） |

### 配置旋钮

`config/env.yaml` 里：

```yaml
rag:
  enable: false
  kb_dir: data/knowledge_db
  docs: '' # 逗号分隔的文件或目录；相对仓库根
```

| 配置         | 作用                                                 |
| ------------ | ---------------------------------------------------- |
| `rag.enable` | 是否启用（与 `docs` 组合，见 `is_rag_enabled`）      |
| `rag.kb_dir` | Chroma 持久化目录                                    |
| `rag.docs`   | 启动时要入库的文档路径列表                           |
| `llm.*`      | 生产环境给 **真实 Embedder**（及可选查询优化 LLM）用 |

工厂入口：`create_knowledge_base` / `ingest_rag_sources`（`src/retrieval/rag_bootstrap.py`）。

### 当前装配现状（重要）

模块与工具类 **已经写好**（含 `SearchDocumentsTool`），但 **`HubloomRuntime` 当前主路径并未挂载知识库 / `search_documents`**——和长期记忆类似：能力在仓库里，默认对话装配还没接到配置开关上。

因此：

- 学模块、验管线 → 跑下面的演示脚本即可；
- 要让在线 Agent 真正会搜文档 → 还需在 Runtime / 示例站装配 `KnowledgeBase` 并注册工具（后续优化）。

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

前面是「管线一览」。这一节按实现讲清：**一片文档进库时发生了什么、块怎么切、检索时怎么拿回来**。  
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
