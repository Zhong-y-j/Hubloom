## 封装 LLM 的设计目的

封装 LLM 的设计，是让代码结构更清晰、更易于复用，让主逻辑可以更专注于智能体的构建。

把「调用大模型」从各个 Agent 里抽出来，集中到 `core` 统一管理。上层只做智能体的推理、路由和协作；下层只管怎么连 API、怎么处理流式和错误。全项目用同一套消息格式和返回格式，避免代码重复，也方便复用和测试。需要更换模型或换供应商，主要改 `core`，不用动 Agent 的核心逻辑。

---

## LLM 封装的模块划分

### models

定义全项目共用的数据结构，与具体厂商 API 字段解耦。主要包括：

- **Role / Message**：多轮对话里「谁说了什么」（system / user / assistant / tool），以及工具回传时需要的 `tool_call_id` 等。
- **ToolCall**：模型发起的一次工具调用（id、函数名、参数）。
- **StopReason**：本轮生成为何结束（正常结束、要调工具、超长截断、错误等）。
- **TokenUsage**：本次调用的 token 用量，便于计费与观测。
- **LLMOutput**：一次调用的统一结果（正文、tool_calls、stop_reason、usage，必要时保留 raw_response 便于排错）。

Agent 拼好 `list[Message]` 交给 core；core 把厂商响应整理成 `LLMOutput`，上层不必解析 OpenAI 的原始 JSON。

### provider

定义 **LLMProvider** 抽象接口，以及流式场景下的事件类型：

- **非流式**：`generate(messages, tools?, stop?, **kwargs) -> LLMOutput`
- **流式**：`generate_stream(...) -> AsyncIterator[LLMStreamEvent]`

流式事件包括（由 core 从厂商 chunk 翻译而来，Agent 只认这些类型）：

- **DeltaEvent**：文本增量，用于边生成边展示。
- **ToolCallStartEvent / ToolCallArgsEvent**：工具调用开始与参数片段（流式 tool calling）。
- **StreamEndEvent**：流结束，携带聚合后的 `LLMOutput`。
- **StreamErrorEvent**：流中途出错。

### llm

**LLM** 类实现 `LLMProvider`，在项目里对接 **OpenAI 兼容 API** 的具体适配器（`AsyncOpenAI`）。职责包括：

- 把 `Message` 列表转成厂商要求的请求格式；
- 发起非流式 / 流式请求；
- 把厂商返回的 delta、tool_calls、finish_reason、usage 等转成 `LLMOutput` 和上述流式事件；
- 对可恢复错误（如限流、超时）配合 **tenacity** 做有限次重试；
- 把 SDK 异常映射为项目内的 `exceptions` 类型。

换线路、换解析逻辑，主要改这一文件；Agent 无感。

### factory：创建 LLM 实例的入口

**create_llm()** 从环境变量（`OPENAI_API_KEY`、`OPENAI_BASE_URL`、`OPENAI_MODEL`）或入参读取配置，构造并返回一个 **`LLMProvider`** 实例（当前默认 `provider="openai"` → `LLM`）。

上层统一写法：`llm = create_llm()`，不在各个 Agent 里散落读密钥和 new 客户端。未来扩展其他厂商时，在 factory 里增加分支即可，调用方不变。

### exceptions

将各类 API / 网络错误收敛为少量类型，Agent 可按类型决定重试、缩短上下文或提示用户：

- **LLMException**：基类
- **ContextLengthExceeded**：上下文超长
- **RateLimitExceeded**：限流（llm 层可能对其实施重试）
- **LLMTimeout**：超时
- **LLMAPIError**：其他 API 错误

避免上层直接判断厂商 SDK 里五花八门的异常类名。

---

## 一次完整调用（谁干什么）

1. **用户**发来一句话。
2. **Agent**结合会话历史、记忆等，整理成 `list[Message]`，并决定用 `generate` 还是 `generate_stream`。
3. **core（LLM）** 请求远程 API 或本地兼容端点，处理流式 chunk、工具调用解析、重试与异常映射。
4. **core** 将结果以 **`LLMOutput`** 或 **流式事件** 还给 Agent。
5. **Agent** 根据结果继续：展示回复、解析意图 JSON、执行工具、路由、写记忆等。

**问模型的细节都在 core；具体「灵枢该怎么想、怎么走」留在 Agent。**

---
