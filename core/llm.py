"""OpenAI 兼容实现类 LLM"""

import json
import time
from openai import AsyncOpenAI
from observability import log, logger
from .provider import *
from .models import *
from .exceptions import *
from tenacity import (
    retry,
    stop_after_attempt,
    wait_exponential,
    retry_if_exception_type,
    RetryError,
)


def _log_llm_request(
    *,
    model: str,
    message_count: int,
    stream: bool,
    has_tools: bool,
) -> float:
    log(
        "llm request",
        model=model,
        messages=message_count,
        stream=stream,
        has_tools=has_tools,
    )
    return time.perf_counter()


def _log_llm_done(*, stream: bool, output: LLMOutput, started_at: float) -> None:
    fields: dict = {
        "stream": stream,
        "stop_reason": output.stop_reason.value,
        "tool_calls": len(output.tool_calls),
        "content_len": len(output.content or ""),
        "duration_ms": round((time.perf_counter() - started_at) * 1000),
    }
    if output.usage:
        fields["prompt_tokens"] = output.usage.prompt_tokens
        fields["completion_tokens"] = output.usage.completion_tokens
        fields["total_tokens"] = output.usage.total_tokens
    log("llm done", **fields)


def _log_llm_failed(exc: Exception, *, stream: bool, phase: str) -> None:
    logger.warning(
        "llm failed | stream={} | phase={} | type={} | detail={}",
        stream,
        phase,
        type(exc).__name__,
        str(exc)[:200],
    )


def _log_llm_retry(retry_state) -> None:
    exc = retry_state.outcome.exception() if retry_state.outcome.failed else None
    logger.warning(
        "llm retry | attempt={} | type={}",
        retry_state.attempt_number,
        type(exc).__name__ if exc else "unknown",
    )


def _llm_retry(max_attempts=3, min_wait=1, max_wait=30):
    """重试：仅「可恢复」类型。限流/超时多试几次有意义；404/鉴权/超长等重试无用。

    以后若要重试「部分 5xx」，不要扩大 LLMAPIError 白名单，改用 retry_if + 判断 status_code。
    """
    return retry(
        stop=stop_after_attempt(max_attempts),
        wait=wait_exponential(multiplier=1, min=min_wait, max=max_wait),
        retry=retry_if_exception_type((RateLimitExceeded, LLMTimeout)),
        before_sleep=_log_llm_retry,
        reraise=True,
    )


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
        model = kwargs.get("model", self.model)
        started_at = _log_llm_request(
            model=model,
            message_count=len(messages),
            stream=True,
            has_tools=bool(tools),
        )
        try:
            params = self._build_params(messages, tools, stop, stream=True, **kwargs)
            stream = await self.client.chat.completions.create(**params)
        except Exception as e:
            mapped = self._map_exception(e)
            _log_llm_failed(mapped, stream=True, phase="request")
            yield StreamErrorEvent(mapped)
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
            mapped = self._map_exception(e)
            _log_llm_failed(mapped, stream=True, phase="stream")
            yield StreamErrorEvent(mapped)
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
                logger.warning(
                    "llm tool args parse failed | stream=true | tool_index={} | tool_name={}",
                    idx,
                    buf.get("name", ""),
                )
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
        _log_llm_done(stream=True, output=final_output, started_at=started_at)
        yield StreamEndEvent(final_output)

    @_llm_retry()
    async def generate(
        self,
        messages: list[Message],
        tools: list[dict] | None = None,
        stop: list[str] | None = None,
        **kwargs,
    ) -> LLMOutput:
        model = kwargs.get("model", self.model)
        started_at = _log_llm_request(
            model=model,
            message_count=len(messages),
            stream=False,
            has_tools=bool(tools),
        )
        try:
            params = self._build_params(messages, tools, stop, stream=False, **kwargs)
            response = await self.client.chat.completions.create(**params)
        except RetryError as e:
            original = e.last_attempt.exception() if e.last_attempt else e
            mapped = self._map_exception(original)
            _log_llm_failed(mapped, stream=False, phase="request")
            raise mapped from original
        except Exception as e:
            mapped = self._map_exception(e)
            _log_llm_failed(mapped, stream=False, phase="request")
            raise mapped from e

        choice = response.choices[0]
        message = choice.message

        # 解析工具调用
        tool_calls: list[ToolCall] = []
        if message.tool_calls:
            for tc in message.tool_calls:
                try:
                    args = (
                        json.loads(tc.function.arguments)
                        if tc.function.arguments
                        else {}
                    )
                except json.JSONDecodeError:
                    logger.warning(
                        "llm tool args parse failed | stream=false | tool_name={}",
                        tc.function.name,
                    )
                    args = {}
                tool_calls.append(
                    ToolCall(id=tc.id, name=tc.function.name, arguments=args)
                )

        fr = choice.finish_reason
        if fr == "tool_calls":
            stop_reason = StopReason.TOOL_CALLS
        elif fr == "length":
            stop_reason = StopReason.LENGTH
        elif fr == "stop":
            stop_reason = StopReason.STOP
        else:
            stop_reason = StopReason.ERROR

        usage = None
        if response.usage:
            u = response.usage
            usage = TokenUsage(u.prompt_tokens, u.completion_tokens, u.total_tokens)

        output = LLMOutput(
            content=message.content or "",
            tool_calls=tool_calls,
            stop_reason=stop_reason,
            usage=usage,
            raw_response=response,
        )
        _log_llm_done(stream=False, output=output, started_at=started_at)
        return output

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
