## RAG 系统的设计目的

RAG（Retrieval-Augmented Generation）系统的设计，是让「外部文档怎么入库、怎么按问题检索」从各个 Agent 里抽出来，集中到 `retrieval/` 统一管理。上层 Agent 只关心何时预取文档、何时调用 `search_documents` 工具；下层由加载器、分块器、向量库（ChromaDB）和可选的查询优化器完成具体实现。

全项目用同一套检索结果格式（`text` + `metadata` + `score`），交给 `ContextAssembler` 拼成 `[DOCUMENTS]` 块，与长期记忆的 `[MEMORY]`、`[GRAPH]` 并列注入 prompt。更换嵌入模型或向量库时，主要改 `retrieval` 与 `embedders`，不必动 Agent 核心逻辑。

`retrieval` 不负责：任务规划、工具编排、记忆提炼——这些由 Agent / `memory` 完成。RAG 只负责**文档知识**的索引与检索。

---

## 与记忆系统的区别

两者都走向量检索，但**数据来源、写入时机、隔离方式**不同，不要混用。

| 维度 | 记忆（`memory/`） | RAG（`retrieval/`） |
| ---- | ----------------- | ------------------- |
| **记什么** | 对话提炼的事实、偏好、实体关系 | 产品手册、政策、技术文档等**外部文件** |
| **写入时机** | 每轮 conversation；回合结束 consolidate | **离线/管理侧**导入（`add_document`），非每轮自动写 |
| **存储** | SQLite + Qdrant + Neo4j | ChromaDB（`persist_dir` 本地持久化） |
| **隔离键** | `namespace` / `session_id` | `doc_id`、collection 名 |
| **怎么取** | `MemoryManager.recall` / `MemoryContextProvider` | `KnowledgeBase.search` |
| **注入 prompt** | `[MEMORY]`、`[GRAPH]` | `[DOCUMENTS]` |
| **Agent 工具** | `search_memory` | `search_documents` |

一句话：**记忆是「和用户聊出来的」；RAG 是「事先灌进去的文档库」。**

---

## 模块划分

```
retrieval/
├── loader.py              # DocumentLoader：多格式 → Markdown
├── semantic_splitter.py   # SemanticSplitter：结构感知分块 + 元数据
├── knowledge_base.py      # KnowledgeBase：入库 + 检索（对外核心）
├── query_optimizer.py     # QueryOptimizer：MQE / HyDE（可选，依赖 core LLM）
└── demo_rag.py            # 冒烟：setup_log + 入库 + 工具检索

embedders/                 # 与 memory 共用抽象
├── base.py                # Embedder 接口
└── openai_embedder.py     # 默认 OpenAIEmbedder

tools/builtin/
└── retrieval_tool.py      # SearchDocumentsTool（search_documents）

memory/context.py          # ContextAssembler：把 RAG 结果格式化为 [DOCUMENTS]
```

| 模块 | 职责 |
| ---- | ---- |
| **DocumentLoader** | PDF/Word/Excel 等经 **MarkItDown** 统一转 Markdown；代码文件以 fenced code block 输出；可注册自定义转换器 |
| **SemanticSplitter** | 按 Markdown `#`、中文编号标题切分；控制 token 块大小与重叠；输出 `{ content, metadata }`（含 `section_path`、`chunk_id` 等） |
| **KnowledgeBase** | 编排 loader → splitter → embed → ChromaDB；对外 `add_document` / `search` / `delete_document` / `clear` |
| **QueryOptimizer** | 用 LLM 做 **MQE**（多查询扩展）或 **HyDE**（假设文档嵌入），提升难检索问题的召回 |
| **Embedder** | 文本 → 向量；入库与检索共用同一实现，保证维度一致 |
| **SearchDocumentsTool** | Agent 可调用的只读工具，内部调用 `kb.search`，返回人类可读的多段文本 |

**原则**：业务层 **只依赖 `KnowledgeBase` 或 `SearchDocumentsTool`**，不直接操作 ChromaDB 或 MarkItDown。

---

## 分层架构：入库链 vs 检索链

```
【写入 / 索引】（低频，脚本或管理 API）
  文件路径
    → DocumentLoader.load()           → Markdown 全文
    → SemanticSplitter.split()        → List[{content, metadata}]
    → Embedder.embed()（分批）         → 向量
    → ChromaDB collection.add()       → ids + documents + embeddings + metadatas

【读取 / 检索】（每轮对话或工具调用）
  用户 query
    →（可选）QueryOptimizer.optimize   → 改写 query / 生成 HyDE 段落
    → Embedder.embed([query])
    → ChromaDB collection.query()     → ANN + distances
    → 格式化 List[{id, text, metadata, score}]
    → ContextAssembler / Tool 格式化   → [DOCUMENTS] 或工具返回字符串
```

ChromaDB 在一条记录里同时存 **原文、向量、元数据**（双通道合一），检索时 `include=["documents", "metadatas", "distances"]`，`score = 1.0 - distance`。

---

## `KnowledgeBase`（`retrieval/knowledge_base.py`）

### 构造

```python
from embedders.openai_embedder import OpenAIEmbedder
from retrieval.knowledge_base import KnowledgeBase
from retrieval.query_optimizer import QueryOptimizer
from core import create_llm

kb = KnowledgeBase(
    embedder=OpenAIEmbedder(),
    persist_dir="data/knowledge_db",      # Chroma 持久化目录
    collection_name="documents",
    query_optimizer=QueryOptimizer(create_llm()),  # 可选；None 则只能用 optimize="none"
)
```

| 参数 | 作用 |
| ---- | ---- |
| `embedder` | 入库与查询共用；须与 collection 已有向量维度一致 |
| `persist_dir` | 本地 Chroma 数据目录 |
| `collection_name` | 集合名，默认 `documents` |
| `query_optimizer` | 注入后 `search(..., optimize="mqe"|"hyde")` 才生效 |

### `add_document`（写入）

| 步骤 | 说明 |
| ---- | ---- |
| 1 | `loader.load(file_path)` → Markdown |
| 2 | `splitter.split()` → 若干 chunk；无块则 warning 并返回 `doc_id` |
| 3 | 为每块生成 `storage_id = {doc_id}_{chunk_id}`，合并文档级元数据（`doc_name`、`source_type`、`indexed_at`） |
| 4 | `embedder.embed` 按 batch（默认 8）写入 |
| 5 | `collection.add` 一次性落库 |

返回 **`doc_id`**（未传则 `uuid` hex）。同一文件重复索引会生成新 `doc_id` 或覆盖策略需业务侧自行约定（当前实现为新增 id）。

### `search`（读取）

```python
results = await kb.search(
    query="请假审批流程",
    top_k=3,
    where=None,                    # Chroma metadata 过滤，如 {"doc_id": "..."}
    optimize="none",               # none | mqe | hyde
)
# results[i]: { "id", "text", "metadata", "score" }
```

| `optimize` | 行为 | 适用场景 |
| ---------- | ---- | -------- |
| `none` | 原 query 直接向量检索 | 明确关键词、预取默认路径 |
| `hyde` | LLM 生成假设答案段落，用段落 embedding 检索 | 抽象/概括性问题（「产品定位是什么」） |
| `mqe` | LLM 生成多个 query 变体，分别检索后去重合并 | 模糊/开放性问题（「有哪些方法」） |

无 `query_optimizer` 时传 `mqe`/`hyde` 会退化为普通检索（与 `none` 等价）。

### 管理接口

- **`delete_document(doc_id)`**：按 `doc_id` 删除该文档全部分块  
- **`clear()`**：删除并重建 collection  
- **`get_document_list()`**：按 `doc_id` 去重列出已索引文档摘要  

---

## `QueryOptimizer`（`retrieval/query_optimizer.py`）

依赖 **`core` 的 `LLMProvider`**（`create_llm()`），与记忆里的 `MemoryConsolidator` 类似，都是「为检索服务的 LLM 侧车」，不参与主对话生成。

| 策略 | 输出 | 检索侧用法 |
| ---- | ---- | ---------- |
| **MQE** | `List[str]` 多个 query 变体 | 对每个变体 `_vector_search`，`_deduplicate_and_sort` 取 top_k |
| **HyDE** | `str` 假设文档段落 | 用段落文本做一次 `_vector_search` |

LLM 失败或空结果时 **回退原 query**（`logger.warning`），不中断主流程。

---

## `SearchDocumentsTool`（`tools/builtin/retrieval_tool.py`）

| 字段 | 说明 |
| ---- | ---- |
| `name` | `search_documents` |
| 参数 | `query`（必填）、`optimize`（`none` / `hyde` / `mqe`） |
| 返回 | 格式化的多段引用（来源、章节、相关度 + 正文）；无结果返回提示文案 |

与 **`search_memory`** 并列，ReAct 等 Agent 可将二者标为只读检索工具；预取 `[DOCUMENTS]` 不足时可由模型主动再调本工具。

---

## 与 `ContextAssembler` 的协作

**分工**：`retrieval` 负责取回结构化片段；`memory/context.py` 的 **`ContextAssembler`** 负责裁剪 Token、格式化成 prompt 块。

ReAct 每轮典型流程（参考 `backup/agents/react/agent.py`）：

1. **`_prefetch_documents(task)`**：`knowledge_base.search(task, top_k=..., optimize="none")`  
2. **`ContextAssembler.assemble(..., documents=hits)`**：GSSC（Gather → Select → Structure → Compress）里把每条 doc 格式化为带来源/章节的候选，最终写入：

```
[system: 人设 + 规则]
[system: [MEMORY]…[/MEMORY]]       ← memory
[system: [GRAPH]…[/GRAPH]]         ← memory（可选）
[system: [DOCUMENTS]…[/DOCUMENTS]] ← RAG
[conversation 最近 N 条]
[user: 当前输入]
```

文档块在 assembler 内优先级约 **50**（低于 system / memory / graph，高于普通 history），并参与 **max_tokens** 预算与 `min_relevance` 过滤。

**注意**：预取一般用 `optimize="none"`（省一次 LLM）；工具调用时可由模型指定 `hyde` / `mqe` 做二次检索。

---

## RAG 的具体工作流程

### 1）写入发生在什么时候？——文档导入时（`retrieval/demo_rag.py`）

`demo_rag.py` 模拟的是 **知识库建设** 阶段，不是每轮对话自动执行：

```python
setup_log()
embedder = OpenAIEmbedder()
kb = KnowledgeBase(embedder=..., persist_dir="data/knowledge_db", query_optimizer=...)

# 通常只执行一次（注释掉 clear / add 可重复跑检索）
doc_id = await kb.add_document("/path/to/manual.docx")
```

- **输入**：本地文件路径  
- **动作**：loader → splitter → embed → Chroma  
- **结果**：持久化到 `persist_dir`；日志见 `rag ingest start` / `rag ingest done`  

一句话：**`add_document` 是「建库」操作，在对话之外、按需触发。**

### 2）读取发生在什么时候？——调 LLM 之前或工具调用时

**路径 A：Agent 预取（读文档）**

```
用户 task
  → kb.search(task, top_k=N, optimize="none")
  → ContextAssembler.assemble(documents=hits)
  → core LLM.generate(messages=...)
```

**路径 B：模型主动调工具**

```
模型发起 tool: search_documents(query=..., optimize="hyde")
  → SearchDocumentsTool.execute
  → kb.search(...)
  → 工具结果字符串回到对话，模型再组织回答
```

**路径 C：仅脚本验证（`demo_rag.py` 后半段）**

```python
tool = SearchDocumentsTool(kb, top_k=3)
text = await tool.execute(query="...", optimize="hyde")
```

一句话：**读取发生在「需要外部文档佐证」时——预取进 prompt，或通过工具二次检索。**

### 3）为什么「建库」和「检索」都在 `KnowledgeBase`？

- **loader / splitter**：无状态工具，被 KB 组合调用  
- **KnowledgeBase**：对外唯一入口，隐藏 Chroma 与分批 embed 细节  
- **QueryOptimizer**：可选增强，不污染 loader 层  
- **SearchDocumentsTool**：Agent 边界适配（字符串格式），与 KB 返回的 dict 列表解耦  

对应原则：

> **入库（ingest）是「沉淀文档」；检索（search）是「按问找片段」；装配（assemble）是「排版进 prompt」。时机与目标不同，分层清晰。**

---

## 一次完整调用（谁干什么）

```
【离线】
  运营/开发者上传文件
    → KnowledgeBase.add_document
    → Chroma 持久化

【在线 · 每轮用户提问】
  用户发话
    → Agent：kb.search 预取（可选）
    → Agent：memory recall 预取（可选）
    → ContextAssembler：拼 [MEMORY] / [GRAPH] / [DOCUMENTS] + 历史 + 当前 user
    → core LLM：生成回复
    →（可选）search_documents 工具补充检索
    → conversation.remember / MemoryConsolidator（与 RAG 无关）
```

**读** RAG 在调 LLM 之前（预取）或工具轮次中；**写** RAG 不在对话环里自动发生。

---

## 日志与观测（`observability`）

入口脚本调用 **`setup_log()`**，默认写入 `logs/debug.log`（或环境变量 `CORTEX_LOG_FILE`），不在控制台重复打日志。

| 位置 | 典型关键字 |
| ---- | ---------- |
| `KnowledgeBase.add_document` | `rag ingest start` / `chunks` / `rag ingest done` |
| `KnowledgeBase.search` | `rag search` / `rag search mqe` / `rag search hyde` / `rag search done`（含 `hits` 预览） |
| `QueryOptimizer` | `rag optimize` / `rag optimize done`；失败 `rag optimize * failed` |
| `SearchDocumentsTool` | `rag tool search` / `rag tool search done` |

不打：完整 chunk 正文、embedding 向量、API key。

---

## 测试与联调入口

| 脚本 | 作用 |
| ---- | ---- |
| `retrieval/demo_rag.py` | 冒烟：日志 + KB + `SearchDocumentsTool`（hyde/mqe/none） |
| `memory/test_context.py` | 仅测 assembler：手工传入 `documents=` 看 `[DOCUMENTS]` 块 |
| `backup/agents/scripts/react_demo.py` | 完整 ReAct + memory + RAG 联调（Agent 在 backup 目录） |

运行示例：

```bash
PYTHONPATH=. uv run python retrieval/demo_rag.py
grep "rag " logs/debug.log | tail -20
```

常见问题（与记忆向量库类似）：HTTP 代理导致 Chroma/Qdrant 超时、**embedding 维度与已有 collection 不一致**（需清空重建或换匹配 embedder）。

---

## 一句话总结

**RAG 封装：把「多格式文档 → 分块 → 向量 → Chroma 检索」收进 `KnowledgeBase` 统一接口；Agent 只管何时预取/调 `search_documents`，`ContextAssembler` 只管怎么拼进 `[DOCUMENTS]`；可选 `QueryOptimizer` 用 LLM 增强难检索问题；换嵌入实现或持久化路径主要改 retrieval 与 embedders，不动智能体核心逻辑。**
