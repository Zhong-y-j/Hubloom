from abc import ABC, abstractmethod
from typing import AsyncIterator

from .models import Message, LLMOutput


class LLMStreamEvent:
    """流式事件基类"""

    pass


class DeltaEvent(LLMStreamEvent):
    """文本增量事件

    使用处：显示实时文本生成进度、优化 UI 响应速度。

    字段说明：
        - delta: 文本增量，通常是单个字符或词组。
    """

    def __init__(self, delta: str):
        self.delta = delta


class ToolCallStartEvent(LLMStreamEvent):
    """工具调用开始事件

    使用处：在工具调用开始时触发，用于显示工具调用开始信息。

    字段说明：
        - call_id: 工具调用 ID。
        - name: 工具名称。
    """

    def __init__(self, call_id: str, name: str):
        self.call_id = call_id
        self.name = name


class ToolCallArgsEvent(LLMStreamEvent):
    """工具调用参数增量事件（JSON 片段）

    使用处：在工具调用参数变化时触发，用于显示工具调用参数变化信息。

    字段说明：
        - call_id: 工具调用 ID。
        - args_delta: 工具调用参数增量，通常是 JSON 片段。
    """

    def __init__(self, call_id: str, args_delta: str):
        self.call_id = call_id
        self.args_delta = args_delta


class StreamEndEvent(LLMStreamEvent):
    """流正常结束，携带聚合的 LLMOutput

    使用处：在流式生成结束时触发，用于显示流式生成结束信息。

    字段说明：
        - output: 流式生成结果，通常是 LLMOutput 对象。
    """

    def __init__(self, output: LLMOutput):
        self.output = output


class StreamErrorEvent(LLMStreamEvent):
    """流出错"""

    def __init__(self, error: Exception):
        self.error = error


class LLMProvider(ABC):
    """
    LLMProvider 是 LLM 大模型模型的抽象基类，提供非流式和流式生成接口。
    """

    @abstractmethod
    async def generate(
        self,
        messages: list[Message],
        tools: list[dict] | None = None,
        stop: list[str] | None = None,
        **kwargs,
    ) -> LLMOutput:
        """
        非流式生成
        :param messages: 消息列表
        :param tools: 工具定义列表，每个 dict 格式：{"name":..., "description":..., "parameters":...}
        :param stop: 停止词列表
        :return: LLMOutput
        """

    @abstractmethod
    async def generate_stream(
        self,
        messages: list[Message],
        tools: list[dict] | None = None,
        stop: list[str] | None = None,
        **kwargs,
    ) -> AsyncIterator[LLMStreamEvent]:
        """
        流式生成，返回事件异步迭代器
        """
