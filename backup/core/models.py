from dataclasses import dataclass, field
from typing import Any, Optional
from enum import Enum


class Role(str, Enum):
    """类型名：Role（枚举）。

    作用：在聊天协议里区分「谁说了这句话」——系统、用户、模型还是工具回传，
    与常见 Chat Completions 类接口里每条消息的 role 字符串一一对应。

    使用处：构造发给模型的多轮 messages 时，每条记录都要带 role；拼历史、
    做 tool calling 循环、或把会话存进数据库/缓存时，也都按同一套角色语义处理。

    取值说明：
        - SYSTEM: 系统层指令（人设、规则、输出格式等）。
        - USER: 用户输入。
        - ASSISTANT: 模型上一轮的文本回复；多轮对话需按顺序写回上下文。
        - TOOL: 外部工具执行后的结果文本；与 tool calling 配套使用。
    """

    SYSTEM = "system"
    USER = "user"
    ASSISTANT = "assistant"
    TOOL = "tool"


@dataclass
class ToolCall:
    """类型名：ToolCall（数据类）。

    作用：表示模型发起的一次可执行工具调用（函数名 + 参数），与 API 返回的
    tool_calls 列表中一项语义一致（此处参数已解析为 dict）。

    使用处：当响应表明需要 tool_calls 时，按 id 执行对应工具，再把结果以
    role=tool 的消息写回上下文（并带上同一 tool_call_id），形成「模型—工具—模型」循环。

    字段说明：
        - id: 本次调用在当轮内的唯一 ID，回传 tool 消息时必须带上同一 id。
        - name: 要调用的工具/函数名。
        - arguments: 入参，已从 JSON 解析为字典。
    """

    id: str
    name: str
    arguments: dict


class StopReason(str, Enum):
    """类型名：StopReason（枚举）。

    作用：描述「这一轮生成为什么结束」，一般从响应里的 finish_reason 映射而来，
    供业务分支（是否截断、是否要走工具等）。

    使用处：读模型响应的元数据时（finish_reason / stop_reason 等字段）；
    客户端据此决定：直接展示、提示截断、还是进入工具执行与多轮补全。

    取值说明：
        - STOP: 正常结束。
        - TOOL_CALLS: 模型要求执行工具，应解析响应中的 tool_calls 再继续对话。
        - LENGTH: 因长度/token 限制被截断，正文可能不完整。
        - ERROR: 请求失败、未知 finish_reason 或己方约定的错误占位。
    """

    STOP = "stop"
    TOOL_CALLS = "tool_calls"
    LENGTH = "length"
    ERROR = "error"


@dataclass
class TokenUsage:
    """类型名：TokenUsage（数据类）。

    作用：记录本次 API 调用在服务端统计的 token 消耗，便于计费、限流与观测。

    使用处：当模型响应包含 usage 时读取并记录；用于成本核算、配额告警、
    按用户/会话聚合统计，或在上层展示「本次消耗」。

    字段说明：
        - prompt_tokens: 输入侧（含历史）消耗的 token 数。
        - completion_tokens: 模型生成内容消耗的 token 数。
        - total_tokens: 合计；通常约等于前两者之和（以服务商定义为准）。
    """

    prompt_tokens: int
    completion_tokens: int
    total_tokens: int


@dataclass
class Message:
    """类型名：Message（数据类）。

    作用：对聊天协议里「一条消息」的结构化表示：谁在说话、说什么，以及工具链所需的附加字段。

    使用处：维护会话历史、拼装请求体中的 messages 数组、持久化与回放对话；
    任何需要把「多轮 + 可选工具」交给模型的地方，都按有序的消息列表传递。

    字段说明：
        - role: 发言者，见 `Role`。
        - content: 文本内容；无正文时可用空串（视协议而定）。
        - tool_calls: 仅 assistant 消息在工具场景下使用：模型要求的若干 `ToolCall`。
        - tool_call_id: 仅 role 为 TOOL 时需要：对应某次 `ToolCall.id`。
        - name: 部分后端要求 tool 消息附带工具名时填写，默认可为 None。
    """

    role: Role
    content: str | list[dict[str, Any]]
    tool_calls: Optional[list[ToolCall]] = None
    tool_call_id: Optional[str] = None
    name: Optional[str] = None


@dataclass
class LLMOutput:
    """类型名：LLMOutput（数据类）。

    作用：把一次模型调用响应里业务常关心的部分（正文、工具请求、结束原因、用量）
    收成稳定结构，隔离具体 SDK/HTTP 形态。

    使用处：应用层消费「单次推理结果」时：渲染给用户、判断是否进入工具执行、
    记录 stop_reason 与 usage、调试时保留原始响应等。

    字段说明：
        - content: 助手可见的文本正文。
        - tool_calls: 若模型请求工具：解析后的调用列表（可能为空列表）。
        - stop_reason: 结束原因，见 `StopReason`。
        - usage: 若响应含 usage；否则 None。
        - raw_response: SDK/HTTP 原始响应对象，排错或透传时用，勿强依赖其结构。
    """

    content: str = ""
    tool_calls: list[ToolCall] = field(default_factory=list)
    stop_reason: StopReason = StopReason.STOP
    usage: Optional[TokenUsage] = None
    raw_response: Any = None
