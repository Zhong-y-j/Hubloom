import json
from openai import AsyncOpenAI
from .provider import *
from .models import *
from .exceptions import *


class LLM(LLMProvider):

    def __init__(
        self,
        api_key: str,
        base_url: str,
        model: str,
        params: dict | None = None,
    ):
        self.api_key = api_key
        self.base_url = base_url
        self.model = model
        self.client = AsyncOpenAI(api_key=api_key, base_url=base_url)
        self.params = params or {}

    async def generate_stream(
        self,
        messages: list[Message],
        tools: list[dict] | None = None,
        stop: list[str] | None = None,
        **kwargs,
    ) -> AsyncIterator[LLMStreamEvent]:
        try:
            params = self._build_params(messages, tools, stop, stream=True, **kwargs)
            stream = await self.client.chat.completions.create(**params)
        except Exception as e:
            yield StreamErrorEvent(self._map_exception(e))
            return

        # 流式状态变量
        content = ""
        # 工具调用聚合缓存：{ index: {id, name, arguments_buffer} }
        tool_buffers: dict[int, dict] = {}
        finish_reason = None
        usage = None

        try:
            async for chunk in stream:
                if not chunk.choices:
                    continue

                delta = chunk.choices[0].delta
                # 文本增量
                if delta and delta.content:
                    content += delta.content
                    yield DeltaEvent(delta.content)

                # 工具调用增量
                if delta and delta.tool_calls:
                    for tc_delta in delta.tool_calls:
                        idx = tc_delta.index
                        if idx not in tool_buffers:
                            tool_buffers[idx] = {
                                "id": "",
                                "name": "",
                                "arguments_buffer": "",
                            }
                        buf = tool_buffers[idx]

                        # id 和 name 只在第一次出现
                        if tc_delta.id:
                            buf["id"] = tc_delta.id
                        if tc_delta.function and tc_delta.function.name:
                            buf["name"] = tc_delta.function.name
                            # 当名称第一次出现时，发送 ToolCallStartEvent
                            yield ToolCallStartEvent(buf["id"], buf["name"])

                        # 参数增量
                        if tc_delta.function and tc_delta.function.arguments:
                            args_delta = tc_delta.function.arguments
                            buf["arguments_buffer"] += args_delta
                            yield ToolCallArgsEvent(buf["id"], args_delta)

                # 收集 usage 和 finish_reason（通常在最后一个 chunk）
                if chunk.usage:
                    usage = TokenUsage(
                        prompt_tokens=chunk.usage.prompt_tokens,
                        completion_tokens=chunk.usage.completion_tokens,
                        total_tokens=chunk.usage.total_tokens,
                    )
                if chunk.choices[0].finish_reason:
                    finish_reason = chunk.choices[0].finish_reason

        except Exception as e:
            yield StreamErrorEvent(self._map_exception(e))
            return

        # 组装最终工具调用列表
        tool_calls = []
        for idx in sorted(tool_buffers.keys()):
            buf = tool_buffers[idx]
            try:
                args = (
                    json.loads(buf["arguments_buffer"])
                    if buf["arguments_buffer"]
                    else {}
                )
            except json.JSONDecodeError:
                args = {}
            tool_calls.append(ToolCall(id=buf["id"], name=buf["name"], arguments=args))

        # 结束原因映射
        if finish_reason == "tool_calls":
            stop_reason = StopReason.TOOL_CALLS
        elif finish_reason == "length":
            stop_reason = StopReason.LENGTH
        elif finish_reason == "stop":
            stop_reason = StopReason.STOP
        else:
            stop_reason = StopReason.ERROR  # 未知或无

        final_output = LLMOutput(
            content=content,
            tool_calls=tool_calls,
            stop_reason=stop_reason,
            usage=usage,
            raw_response=None,
        )
        yield StreamEndEvent(final_output)

    async def generate(
        self,
        messages: list[Message],
        tools: list[dict] | None = None,
        stop: list[str] | None = None,
        **kwargs,
    ) -> LLMOutput:
        pass

    # 构建请求参数
    def _build_params(
        self,
        messages: list[Message],
        tools: list[dict] | None,
        stop: list[str] | None,
        stream: bool,
        **kwargs,
    ) -> dict:
        params = {
            "model": kwargs.pop("model", self.model),
            "messages": self._convert_messages(messages),
            "stream": stream,
            **self.params,
        }

        if tools:
            params["tools"] = self._convert_tools(tools)
        if stop:
            params["stop"] = stop
        params.update(kwargs)  # 允许覆盖
        return params

    def _convert_messages(self, messages: list[Message]) -> list[dict]:
        converted = []
        for msg in messages:
            msg_dict: dict[str, Any] = {"role": msg.role.value, "content": msg.content}

            if msg.tool_calls:
                msg_dict["tool_calls"] = [
                    {
                        "id": tc.id,
                        "type": "function",
                        "function": {
                            "name": tc.name,
                            "arguments": json.dumps(tc.arguments, ensure_ascii=False),
                        },
                    }
                    for tc in msg.tool_calls
                ]
            if msg.tool_call_id:
                msg_dict["tool_call_id"] = msg.tool_call_id
            if msg.name:
                msg_dict["name"] = msg.name
            converted.append(msg_dict)
        return converted

    def _convert_tools(self, tools: list[dict] | None) -> list[dict] | None:
        if not tools:
            return None
        return [{"type": "function", "function": tool} for tool in tools]

    def _map_exception(self, e: Exception) -> Exception:
        """将 openai 的异常映射为我们的异常"""
        from openai import (
            RateLimitError as OpenAIRateLimitError,
            APITimeoutError,
            APIError,
            BadRequestError,
        )

        if isinstance(e, OpenAIRateLimitError):
            return RateLimitExceeded(str(e))
        if isinstance(e, APITimeoutError):
            return LLMTimeout(str(e))
        if isinstance(e, BadRequestError):
            # 可能包含 context_length_exceeded
            if "context_length_exceeded" in str(e):
                return ContextLengthExceeded(str(e))
            return LLMAPIError(str(e))
        if isinstance(e, APIError):
            return LLMAPIError(str(e))
        return LLMAPIError(str(e))
