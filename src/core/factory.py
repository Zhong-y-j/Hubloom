"""根据配置创建具体 LLM 实例（调用方显式传参，不读 OPENAI_* 环境变量）。"""

from observability import log
from .llm import LLM
from .provider import LLMProvider


def _with_thinking_params(params: dict | None, *, enable_thinking: bool) -> dict:
    merged = dict(params or {})
    if not enable_thinking:
        return merged
    extra = dict(merged.get("extra_body") or {})
    extra.setdefault("enable_thinking", True)
    merged["extra_body"] = extra
    return merged


def create_llm(
    provider: str = "openai",
    api_key: str | None = None,
    base_url: str | None = None,
    model: str | None = None,
    params: dict | None = None,
    *,
    enable_thinking: bool = False,
) -> LLMProvider:

    provider = provider.lower()
    key = (api_key or "").strip()
    if not key:
        log("create_llm failed", provider=provider, reason="api_key not provided")
        raise ValueError(
            "create_llm requires api_key=... "
            "(pass HubloomConfig.openai_api_key or request context)"
        )
    api_key = key
    merged_params = _with_thinking_params(params, enable_thinking=enable_thinking)
    if provider == "openai":
        llm = LLM(
            api_key=api_key,
            base_url=base_url,
            model=model,
            params=merged_params,
        )
        log(
            "create_llm ok",
            provider=provider,
            model=model,
            base_url=base_url or "(default)",
            enable_thinking=enable_thinking,
        )
        return llm
    # 未来可在此扩展其他 provider
    log("create_llm failed", provider=provider, reason="unsupported provider")
    raise ValueError(f"Unsupported LLM provider: {provider}")


if __name__ == "__main__":
    from observability import setup_log

    setup_log()  # 仅写 logs/agentcortex.log，不在终端打 log

    from .models import Message, Role
    from .provider import (
        DeltaEvent,
        ReasoningDeltaEvent,
        StreamEndEvent,
        StreamErrorEvent,
        ToolCallArgsEvent,
        ToolCallStartEvent,
    )
    import asyncio

    async def main():
        from hubloom.config import HubloomConfig

        cfg = HubloomConfig.from_file("config/env.yaml")
        llm = create_llm(
            api_key=cfg.openai_api_key,
            model=cfg.openai_model,
            base_url=cfg.openai_base_url,
        )
        messages = [
            Message(role=Role.USER, content="你好啊?"),
        ]
        print("--- 流式输出 ---")
        thinking_started = False
        content_started = False
        async for event in llm.generate_stream(messages):
            if isinstance(event, ReasoningDeltaEvent):
                if not thinking_started:
                    print("\n[thinking] ", end="", flush=True)
                    thinking_started = True
                print(event.delta, end="", flush=True)
            elif isinstance(event, DeltaEvent):
                if not content_started:
                    print("\n[content] ", end="", flush=True)
                    content_started = True
                print(event.delta, end="", flush=True)
            elif isinstance(event, ToolCallStartEvent):
                print(f"\n[tool_start] id={event.call_id} name={event.name}")
            elif isinstance(event, ToolCallArgsEvent):
                print(f"[tool_args] id={event.call_id} {event.args_delta}", end="")
            elif isinstance(event, StreamEndEvent):
                out = event.output
                print("\n--- 流结束 ---")
                if out.thinking:
                    print(f"thinking: {out.thinking!r}")
                print(f"content: {out.content!r}")
                print(f"stop_reason: {out.stop_reason}")
                if out.tool_calls:
                    print(f"tool_calls: {out.tool_calls}")
                if out.usage:
                    print(
                        f"usage: prompt={out.usage.prompt_tokens} "
                        f"completion={out.usage.completion_tokens} "
                        f"total={out.usage.total_tokens}"
                    )
            elif isinstance(event, StreamErrorEvent):
                print(f"\n[error] {type(event.error).__name__}: {event.error}")
            else:
                print(f"\n[unknown] {event!r}")

    asyncio.run(main())
